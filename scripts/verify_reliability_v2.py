import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "core"))

from jarvis_core.config import CoreSettings
from jarvis_core.integrations.bookshell import BookShellClient
from jarvis_core.services import JarvisServices


async def main() -> None:
    timings = []
    fixture_date = "2099-12-30"
    fixture_title = f"JARVIS verificación {uuid4()}"
    client = BookShellClient()

    with tempfile.TemporaryDirectory(prefix="jarvis-v2-", ignore_cleanup_errors=True) as data_dir:
        services = JarvisServices(CoreSettings(data_dir=Path(data_dir)))
        await services.ollama.warm()

        async def run(name: str, message: str) -> dict:
            started = time.perf_counter()
            first = None

            async def chunk(_value: str) -> None:
                nonlocal first
                first = first or time.perf_counter()

            result = await services.chat_stream(
                {"message": message, "turn_id": f"verify-{uuid4()}"}, chunk
            )
            ended = time.perf_counter()
            timings.append({
                "scenario": name,
                "ttft_ms": round(((first or ended) - started) * 1000, 1),
                "total_ms": round((ended - started) * 1000, 1),
                "answer": result["message"],
            })
            return result

        before = await client.current_book()
        if not before.get("found") or before["book"].get("currentPage") != 221:
            raise RuntimeError(f"Expected current page 221 before verification, got {before}")

        await run("book_current", "¿Qué libro estoy leyendo?")
        await run("book_page", "¿Por qué página voy?")
        await run("page_write_220", "Apunta página 220")
        at_220 = await client.current_book()
        if at_220["book"].get("currentPage") != 220:
            raise RuntimeError("BookShell did not persist page 220")
        await run("page_restore_221", "Apunta página 221")
        restored = await client.current_book()
        if restored["book"].get("currentPage") != 221:
            raise RuntimeError("BookShell did not restore page 221")

        await run("reminders_today", "¿Qué tengo hoy?")
        await run(
            "reminder_create",
            f"Recuérdame {fixture_title} el {fixture_date} a las 23:41",
        )
        reminders = await client._request("GET", "/reminders", params={"from": fixture_date, "until": fixture_date, "limit": 100})
        saved = next((item for item in reminders.get("reminders", []) if fixture_title in str(item.get("title"))), None)
        if not saved or saved.get("targetTime") != "23:41":
            raise RuntimeError("Reminder read-back failed")
        await client._request("PATCH", f"/reminders/{saved['id']}", json={"status": "cancelled"})
        after_cancel = await client._request("GET", "/reminders", params={"from": fixture_date, "until": fixture_date, "limit": 100})
        cancelled = next((item for item in after_cancel.get("reminders", []) if str(item.get("id")) == str(saved["id"])), None)
        if cancelled and cancelled.get("status") != "cancelled":
            raise RuntimeError("Reminder cancellation was not persisted")
        cancelled_status = cancelled.get("status") if cancelled else "absent"

        await run("normal", "¿Cómo estás? Responde en una frase.")
        services.storage.close()

    print(json.dumps({
        "book_before": before["book"], "book_at_220": at_220["book"], "book_restored": restored["book"],
        "reminder": {"id": saved["id"], "date": saved.get("targetDate"), "time": saved.get("targetTime"), "status_after": cancelled_status},
        "timings": timings,
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
