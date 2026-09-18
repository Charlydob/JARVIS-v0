import sqlite3
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                turn_id TEXT,
                tools_available TEXT NOT NULL DEFAULT '[]',
                tools_used TEXT NOT NULL DEFAULT '[]',
                tool_results TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id),
                rating TEXT NOT NULL CHECK(rating IN ('good', 'bad')),
                reward INTEGER CHECK(reward IN (-1, 1)),
                reason TEXT,
                correction TEXT,
                reason_code TEXT,
                comment TEXT,
                expected_behavior TEXT,
                user_message TEXT,
                assistant_response TEXT,
                tools_available TEXT NOT NULL DEFAULT '[]',
                tools_used TEXT NOT NULL DEFAULT '[]',
                tool_results TEXT NOT NULL DEFAULT '[]',
                turn_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        feedback_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(feedback)").fetchall()
        }
        message_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        with self.connection:
            if "reward" not in feedback_columns:
                self.connection.execute("ALTER TABLE feedback ADD COLUMN reward INTEGER")
            if "reason" not in feedback_columns:
                self.connection.execute("ALTER TABLE feedback ADD COLUMN reason TEXT")
            for name, declaration in {
                "reason_code": "TEXT", "comment": "TEXT", "expected_behavior": "TEXT",
                "user_message": "TEXT", "assistant_response": "TEXT",
                "tools_available": "TEXT NOT NULL DEFAULT '[]'", "tools_used": "TEXT NOT NULL DEFAULT '[]'",
                "tool_results": "TEXT NOT NULL DEFAULT '[]'", "turn_id": "TEXT",
            }.items():
                if name not in feedback_columns:
                    self.connection.execute(f"ALTER TABLE feedback ADD COLUMN {name} {declaration}")
            for name, declaration in {
                "turn_id": "TEXT", "tools_available": "TEXT NOT NULL DEFAULT '[]'",
                "tools_used": "TEXT NOT NULL DEFAULT '[]'", "tool_results": "TEXT NOT NULL DEFAULT '[]'",
            }.items():
                if name not in message_columns:
                    self.connection.execute(f"ALTER TABLE messages ADD COLUMN {name} {declaration}")
            self.connection.execute(
                "UPDATE feedback SET reward = CASE rating WHEN 'good' THEN 1 ELSE -1 END WHERE reward IS NULL"
            )

    def add_message(
        self, conversation_id: str, role: str, content: str, *, turn_id: str | None = None,
        tools_available: list[str] | None = None, tools_used: list[str] | None = None,
        tool_results: list[Any] | None = None,
    ) -> str:
        message_id = str(uuid4())
        with self.connection:
            self.connection.execute(
                """INSERT INTO messages(
                    id, conversation_id, role, content, created_at, turn_id,
                    tools_available, tools_used, tool_results
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id, conversation_id, role, content, utc_now(), turn_id,
                    json.dumps(tools_available or [], ensure_ascii=False),
                    json.dumps(tools_used or [], ensure_ascii=False),
                    json.dumps(tool_results or [], ensure_ascii=False),
                ),
            )
        return message_id

    def conversation(self, conversation_id: str, limit: int = 20) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                   f.rating, f.reward, f.reason, f.correction, f.reason_code, f.comment,
                   f.expected_behavior
            FROM messages m
            LEFT JOIN feedback f ON f.message_id = m.id
            ORDER BY m.created_at DESC, m.rowid DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM messages) AS messages,
                (SELECT COUNT(*) FROM feedback WHERE rating = 'good') AS positives,
                (SELECT COUNT(*) FROM feedback WHERE rating = 'bad') AS negatives
            """
        ).fetchone()
        return {
            "messages": int(row["messages"]),
            "positives": int(row["positives"]),
            "negatives": int(row["negatives"]),
        }

    def memories(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, content, metadata, created_at FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def add_feedback(
        self, message_id: str, rating: str, correction: str | None = None, reason: str | None = None,
        *, reason_code: str | None = None, comment: str | None = None,
        expected_behavior: str | None = None,
    ) -> str:
        message = self.connection.execute(
            """SELECT id, conversation_id, rowid, content, turn_id, tools_available, tools_used, tool_results
               FROM messages WHERE id = ? AND role = 'assistant'""", (message_id,)
        ).fetchone()
        if message is None:
            raise ValueError("The assistant message does not exist")
        feedback_id = str(uuid4())
        user = self.connection.execute(
            """SELECT content FROM messages
               WHERE conversation_id = ? AND role = 'user' AND rowid < ?
               ORDER BY rowid DESC LIMIT 1""",
            (message["conversation_id"], message["rowid"]),
        ).fetchone()
        resolved_reason = reason_code or reason
        resolved_expected = expected_behavior or correction
        with self.connection:
            self.connection.execute("DELETE FROM feedback WHERE message_id = ?", (message_id,))
            self.connection.execute(
                """INSERT INTO feedback(
                    id, message_id, rating, reward, reason, correction, reason_code, comment,
                    expected_behavior, user_message, assistant_response, tools_available,
                    tools_used, tool_results, turn_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    feedback_id, message_id, rating, 1 if rating == "good" else -1,
                    resolved_reason, correction, resolved_reason, comment, resolved_expected,
                    str(user["content"]) if user else "", str(message["content"]),
                    str(message["tools_available"] or "[]"), str(message["tools_used"] or "[]"),
                    str(message["tool_results"] or "[]"), message["turn_id"], utc_now(),
                ),
            )
        return feedback_id

    def feedback_examples(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT f.id AS feedback_id, f.rating, f.reward,
                   COALESCE(f.reason_code, f.reason) AS reason_code,
                   f.reason, f.correction, f.comment, f.expected_behavior, f.created_at,
                   COALESCE(NULLIF(f.assistant_response, ''), assistant.content) AS assistant_response,
                   COALESCE(NULLIF(f.user_message, ''), (
                       SELECT user.content FROM messages user
                       WHERE user.conversation_id = assistant.conversation_id
                         AND user.role = 'user' AND user.rowid < assistant.rowid
                       ORDER BY user.rowid DESC LIMIT 1
                   )) AS user_message,
                   f.tools_available, f.tools_used, f.tool_results, f.turn_id
            FROM feedback f
            JOIN messages assistant ON assistant.id = f.message_id
            WHERE assistant.role = 'assistant'
            ORDER BY f.created_at DESC, f.rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows if row["user_message"]]

    def close(self) -> None:
        self.connection.close()
