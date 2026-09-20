import hashlib
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from jarvis_core.tools import Tool, ToolRegistry


LOGGER = logging.getLogger("jarvis-core.bookshell.reminders")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _match(query: str, rows: list[dict[str, Any]], field: str = "name") -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    wanted = _norm(query)
    ranked = sorted(
        ((max(SequenceMatcher(None, wanted, _norm(row.get(field))).ratio(), 1.0 if wanted == _norm(row.get(field)) else 0.0), row) for row in rows),
        key=lambda pair: pair[0], reverse=True,
    )
    if not ranked or ranked[0][0] < 0.45:
        return None, []
    if len(ranked) > 1 and ranked[0][0] < 0.82 and ranked[0][0] - ranked[1][0] < 0.12:
        return None, [row for _, row in ranked[:3]]
    return ranked[0][1], []


def _date_from_ms(value: Any, timezone: ZoneInfo) -> str | None:
    try:
        number = float(value or 0)
        if number <= 0:
            return None
        return datetime.fromtimestamp(number / 1000, timezone).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


class BookShellDomains:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.zone = ZoneInfo(client.timezone)

    def today(self) -> str:
        return datetime.now(self.zone).date().isoformat()

    def _reminder_range(self, scope: str, arguments: dict[str, Any]) -> tuple[str, str]:
        today = datetime.now(self.zone).date()
        if scope == "today":
            return today.isoformat(), today.isoformat()
        if scope == "tomorrow":
            tomorrow = today + timedelta(days=1)
            return tomorrow.isoformat(), tomorrow.isoformat()
        monday = today - timedelta(days=today.weekday())
        if scope == "this_week":
            return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
        if scope == "next_week":
            next_monday = monday + timedelta(days=7)
            return next_monday.isoformat(), (next_monday + timedelta(days=6)).isoformat()
        return str(arguments.get("from") or ""), str(arguments.get("until") or "")

    def _reminder_temporal_state(self, item: dict[str, Any]) -> str:
        status = str(item.get("status") or "pending").casefold()
        if status == "completed":
            return "completado"
        if status in {"expired", "cancelled"}:
            return "vencido" if status == "expired" else "cancelado"
        target_date = str(item.get("targetDate") or "")
        target_time = str(item.get("targetTime") or "23:59")
        try:
            target = datetime.fromisoformat(f"{target_date}T{target_time}").replace(tzinfo=self.zone)
        except ValueError:
            return "pendiente"
        return "vencido" if target < datetime.now(self.zone) else "próximo"

    async def gym_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = await self.client.data("gym/gym") or {}
        workouts = self._workouts(root)
        mode = str(arguments.get("mode") or "last")
        limit = min(30, max(1, int(arguments.get("limit") or 10)))
        if not workouts:
            return {"items": [], "message": "No hay sesiones de gimnasio registradas."}
        if mode in {"last", "days_since"}:
            item = self._workout_summary(workouts[0])
            last_date = datetime.fromisoformat(item["date"]).date()
            item["daysSince"] = (datetime.now(self.zone).date() - last_date).days
            return {"workout": item}
        if mode == "recent":
            return {"items": [self._workout_summary(item) for item in workouts[:limit]]}
        if mode == "exercise":
            query = str(arguments.get("exercise") or "")
            results = []
            for workout in workouts:
                for exercise_id, exercise in (workout.get("exercises") or {}).items():
                    name = str(exercise.get("nameSnapshot") or (root.get("exercises") or {}).get(exercise_id, {}).get("name") or "")
                    if _norm(query) not in _norm(name):
                        continue
                    results.append({
                        "workoutId": workout.get("id"), "date": workout.get("date"), "exerciseId": exercise_id,
                        "exercise": name, "sets": exercise.get("sets") or [],
                    })
            return {"items": results[:limit], "count": len(results)}
        return {"error": "unsupported_mode"}

    async def gym_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "create")
        root = await self.client.data("gym/gym") or {}
        now = int(time.time() * 1000)
        date = str(arguments.get("date") or self.today())
        if action == "update":
            session_id = str(arguments.get("session_id") or "")
            found = next((row for row in self._workouts(root) if str(row.get("id")) == session_id), None)
            if not found:
                return {"updated": False, "message": "No encuentro esa sesión."}
            patch = {"updatedAt": now}
            if arguments.get("name"):
                patch["name"] = str(arguments["name"])
            write_started = time.perf_counter(); await self.client.patch_data(f"gym/gym/workouts/{found['date']}/{session_id}", patch); write_ms = (time.perf_counter() - write_started) * 1000
            readback_started = time.perf_counter()
            persisted = await self.client.data("gym/gym") or {}
            readback_ms = (time.perf_counter() - readback_started) * 1000
            saved = ((persisted.get("workouts") or {}).get(found["date"]) or {}).get(session_id)
            verified = bool(saved) and all(saved.get(key) == value for key, value in patch.items())
            return {"updated": verified, "verified": verified, "sessionId": session_id, "patch": patch, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}

        workout_id = str(uuid4())
        exercises: dict[str, Any] = {}
        catalog = [{"id": key, **value} for key, value in (root.get("exercises") or {}).items() if isinstance(value, dict)]
        requested_exercises = arguments.get("exercises") or []
        if isinstance(requested_exercises, str):
            try:
                requested_exercises = json.loads(requested_exercises)
            except json.JSONDecodeError:
                return {"created": False, "clarificationRequired": True, "message": "No pude interpretar los ejercicios."}
        for index, requested in enumerate(requested_exercises):
            selected, candidates = _match(str(requested.get("name") or ""), catalog)
            if candidates:
                return {"created": False, "ambiguous": True, "candidates": [row.get("name") for row in candidates]}
            exercise_id = str(selected.get("id")) if selected else f"jarvis-{index}-{uuid4()}"
            sets = requested.get("sets")
            if isinstance(sets, int):
                sets = [{"reps": requested.get("reps"), "kg": requested.get("kg"), "done": True} for _ in range(sets)]
            exercises[exercise_id] = {
                "nameSnapshot": selected.get("name") if selected else str(requested.get("name") or "Ejercicio"),
                "typeSnapshot": "strength", "strengthTypeSnapshot": "reps", "originalIndex": index,
                "unilateralSnapshot": bool(selected.get("unilateral")) if selected else False,
                "muscleGroupsSnapshot": selected.get("muscleGroups", []) if selected else [],
                "useBodyweight": bool(selected.get("useBodyweight")) if selected else False,
                "sets": sets if isinstance(sets, list) else [],
            }
        finished = now
        workout = {
            "id": workout_id, "date": date, "name": str(arguments.get("name") or "Entrenamiento"),
            "startedAt": now, "finishedAt": finished, "durationSec": 0,
            "emojiSnapshot": None, "exercises": exercises, "totalReps": sum(int(s.get("reps") or 0) for e in exercises.values() for s in e["sets"]),
            "totalVolumeKg": sum(float(s.get("kg") or 0) * int(s.get("reps") or 0) for e in exercises.values() for s in e["sets"]),
            "updatedAt": now,
        }
        idempotency_key = str(arguments.get("idempotency_key") or hashlib.sha256(json.dumps({"date": date, "name": workout["name"], "exercises": exercises}, sort_keys=True).encode()).hexdigest())
        write_started = time.perf_counter(); payload = await self.client._request("POST", "/jarvis/gym/sessions", json={**workout, "idempotencyKey": idempotency_key}, headers={"Idempotency-Key": idempotency_key}); write_ms = (time.perf_counter() - write_started) * 1000
        readback_started = time.perf_counter()
        persisted = await self.client.data("gym/gym") or {}
        readback_ms = (time.perf_counter() - readback_started) * 1000
        saved_id = str((payload.get("workout") or {}).get("id") or workout_id)
        saved = ((persisted.get("workouts") or {}).get(date) or {}).get(saved_id)
        verified = bool(saved)
        return {"created": verified, "verified": verified, "workout": self._workout_summary(saved or workout), "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}

    async def habits_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = await self.client.data("habits") or {}
        habits = self._habits(root)
        date = str(arguments.get("date") or self.today())
        if _norm(date) in {"today", "hoy"}:
            date = self.today()
        elif _norm(date) in {"tomorrow", "manana"}:
            date = (datetime.now(self.zone).date() + timedelta(days=1)).isoformat()
        name = str(arguments.get("name") or "").strip()
        mode = str(arguments.get("mode") or "list")
        if name:
            chosen, candidates = _match(name, habits)
            if candidates:
                return {"ambiguous": True, "candidates": [item["name"] for item in candidates]}
            if not chosen:
                return {"found": False, "message": "No encuentro ese hábito."}
            return {"found": True, "habit": self._habit_status(root, chosen, date)}
        statuses = [self._habit_status(root, habit, date) for habit in habits if self._scheduled(habit, date)]
        if mode == "pending":
            statuses = [status for status in statuses if not status["completed"]]
        return {"date": date, "items": statuses, "count": len(statuses)}

    async def habits_mark(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = await self.client.data("habits") or {}
        habits = self._habits(root)
        chosen, candidates = _match(str(arguments.get("name") or ""), habits)
        if candidates:
            return {"updated": False, "ambiguous": True, "candidates": [item["name"] for item in candidates]}
        if not chosen:
            return {"updated": False, "message": "No encuentro ese hábito."}
        date = str(arguments.get("date") or self.today())
        completed = bool(arguments.get("completed", True))
        if not completed and not arguments.get("confirmed"):
            return {"updated": False, "confirmationRequired": True, "message": "Confirma que quieres desmarcar el hábito."}
        goal = str(chosen.get("goal") or "check")
        value = arguments.get("value", 1 if goal == "count" else completed)
        payload = await self.client._request("POST", "/jarvis/habits/mark", json={
            "habitId": str(chosen["id"]), "date": date, "completed": completed,
            "value": value, "unit": str(arguments.get("unit") or "minutes"),
        })
        habit = payload.get("habit") or {}
        return {"updated": bool(payload.get("updated")) and bool(payload.get("verified")), "verified": bool(payload.get("verified")), **habit}

    async def finance_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = await self.client.data("finance/finance") or {}
        mode = str(arguments.get("mode") or "movements")
        accounts = self._accounts(root)
        categories = self._categories(root)
        if mode == "accounts":
            return {"items": accounts}
        if mode == "categories":
            return {"items": categories}
        filters = dict(arguments)
        period = str(arguments.get("period") or "")
        today = datetime.now(self.zone).date()
        if period == "today":
            filters.update(from_date=today.isoformat(), until_date=today.isoformat())
        elif period == "week":
            filters.update(from_date=(today - timedelta(days=today.weekday())).isoformat(), until_date=today.isoformat())
        elif period == "month":
            filters.update(from_date=today.replace(day=1).isoformat(), until_date=today.isoformat())
        movements = self._movements(root, filters)
        if mode == "latest":
            return {"movement": movements[0] if movements else None}
        if mode == "summary":
            return {
                "from": arguments.get("from_date"), "until": arguments.get("until_date"),
                "expenses": round(sum(float(item.get("totalEUR") or item.get("amount") or 0) for item in movements if item.get("type") == "expense"), 2),
                "income": round(sum(float(item.get("totalEUR") or item.get("amount") or 0) for item in movements if item.get("type") == "income"), 2),
                "count": len(movements),
            }
        return {"items": movements[: min(100, int(arguments.get("limit") or 20))], "count": len(movements)}

    async def finance_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.client.headers.get("Authorization"):
            return {
                "created": False, "configurationRequired": True,
                "message": "Falta JARVIS_BOOKSHELL_API_TOKEN. No se ha creado ningún movimiento.",
            }
        movement_type = str(arguments.get("type") or "expense")
        root = await self.client.data("finance/finance") or {}
        accounts = self._accounts(root)
        transactions = [value for value in (root.get("transactions") or {}).values() if isinstance(value, dict)]
        from_name = str(arguments.get("from_account") or arguments.get("account") or "")
        to_name = str(arguments.get("to_account") or "")
        inferred = self._infer_finance(transactions, str(arguments.get("description") or ""), movement_type)
        source, ambiguous = _match(from_name, accounts) if from_name else (None, [])
        if source is None and inferred.get("accountId"):
            source = next((row for row in accounts if row["id"] == inferred["accountId"]), None)
        target, target_ambiguous = _match(to_name, accounts) if to_name else (None, [])
        if ambiguous or target_ambiguous:
            return {"created": False, "clarificationRequired": True, "message": "¿Qué cuenta concreta debo usar?"}
        if movement_type != "transfer" and not source:
            return {"created": False, "clarificationRequired": True, "message": "¿En qué cuenta registro el movimiento?"}
        if movement_type == "transfer" and (not source or not target):
            return {"created": False, "clarificationRequired": True, "message": "¿Entre qué dos cuentas hago la transferencia?"}
        category = str(arguments.get("category") or inferred.get("category") or "")
        if movement_type != "transfer" and not category:
            return {"created": False, "clarificationRequired": True, "message": "¿Qué categoría debo usar?"}
        body = {
            "type": movement_type, "amount": float(arguments["amount"]), "currency": str(arguments.get("currency") or ""),
            "date": str(arguments.get("date") or self.today()), "accountId": source.get("id") if movement_type != "transfer" else "",
            "fromAccountId": source.get("id") if source else "", "toAccountId": target.get("id") if target else "",
            "category": category, "description": str(arguments.get("description") or ""),
        }
        bucket = datetime.now(self.zone).strftime("%Y%m%d%H%M")
        idem = str(arguments.get("idempotency_key") or hashlib.sha256((json.dumps(body, sort_keys=True) + bucket).encode()).hexdigest())
        write_started = time.perf_counter(); payload = await self.client._request("POST", "/jarvis/finance/movements", json=body, headers={"Idempotency-Key": idem}); write_ms = (time.perf_counter() - write_started) * 1000
        movement_id = str(payload.get("movementId") or payload.get("id") or "")
        readback_started = time.perf_counter(); persisted = await self.client.data("finance/finance") or {}; readback_ms = (time.perf_counter() - readback_started) * 1000
        saved = (persisted.get("transactions") or {}).get(movement_id) if movement_id else None
        verified = bool(saved)
        return {**payload, "created": verified, "verified": verified, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}, **({"message": "El movimiento no aparece al volver a consultar BookShell."} if not verified else {})}

    async def reminders_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        params = {key: arguments[key] for key in ("status", "from", "until", "limit") if arguments.get(key) is not None}
        params.setdefault("limit", 100)
        params.setdefault("status", "pending")
        scope = str(arguments.get("scope") or "")
        range_from, range_until = self._reminder_range(scope, arguments)
        if scope:
            params["range"] = scope
        elif range_from:
            params["from"] = range_from
        if not scope and range_until:
            params["until"] = range_until
        if arguments.get("query"):
            params["q"] = arguments["query"]
        if arguments.get("person"):
            params["subject"] = arguments["person"]
        if arguments.get("event_type"):
            params["eventType"] = arguments["event_type"]
        if arguments.get("temporal_scope"):
            params["temporalScope"] = arguments["temporal_scope"]
        payload = await self.client._request(
            "GET", "/jarvis/reminders", params=params,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        items = [
            item for item in list(payload.get("reminders") or [])
            if str(item.get("status") or "pending").casefold() != "cancelled"
        ]
        for item in items:
            item["temporalState"] = self._reminder_temporal_state(item)
        trace = dict(getattr(self.client, "last_trace", {}) or {})
        LOGGER.info(
            "route_domain=reminders route_operation=read date_range=%s..%s tool=bookshell_reminders_query request_path=%s http_status=%s result_count=%d",
            range_from or "none", range_until or "none", trace.get("request_path", "/jarvis/reminders"),
            trace.get("http_status", "unknown"), len(items),
        )
        return {
            "items": items, "count": len(items), "range": scope or "custom",
            "dateRange": {"from": range_from or None, "until": range_until or None},
            "_trace": {
                "request_path": trace.get("request_path", "/jarvis/reminders"),
                "http_status": trace.get("http_status"), "result_count": len(items),
            },
        }

    async def reminder_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reminder_id = str(arguments["reminder_id"])
        action = str(arguments.get("action") or "update")
        if action == "cancel" and not arguments.get("confirmed"):
            return {"updated": False, "confirmationRequired": True, "message": "Confirma la cancelación del recordatorio."}
        patch: dict[str, Any] = {}
        if action == "complete":
            payload = await self.client._request("POST", f"/jarvis/reminders/{reminder_id}/complete", json={})
        elif action == "cancel":
            payload = await self.client._request("DELETE", f"/jarvis/reminders/{reminder_id}")
        else:
            mapping = {"title": "title", "target_date": "targetDate", "target_time": "targetTime", "description": "description"}
            patch = {target: arguments[source] for source, target in mapping.items() if arguments.get(source) is not None}
            payload = await self.client._request("PATCH", f"/jarvis/reminders/{reminder_id}", json=patch)
        readback = await self.client._request("GET", f"/jarvis/reminders/{reminder_id}")
        saved = readback.get("reminder") or {}
        expected_status = "completed" if action == "complete" else "cancelled" if action == "cancel" else None
        verified = bool(saved) and (saved.get("status") == expected_status if expected_status else all(saved.get(key) == value for key, value in patch.items()))
        return {"updated": verified, "verified": verified, "reminder": saved or payload.get("reminder")}

    async def world_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = await self.client.data("world") or {}
        scope = str(arguments.get("scope") or "all")
        branches = [scope] if scope in {"saved", "places", "geography", "stays"} else ["saved", "places", "geography", "stays"]
        rows = [{"id": key, "scope": branch, **value} for branch in branches for key, value in (root.get(branch) or {}).items() if isinstance(value, dict)]
        for field in ("query", "city", "category", "country"):
            wanted = _norm(arguments.get(field))
            if wanted:
                target_fields = ["name", "label", "note", "address"] if field == "query" else [field]
                rows = [row for row in rows if any(wanted in _norm(row.get(name)) for name in target_fields)]
        rows.sort(key=lambda row: int(row.get("updatedAt") or row.get("createdAt") or 0), reverse=True)
        return {"items": rows[: min(50, int(arguments.get("limit") or 20))], "count": len(rows)}

    async def world_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "create")
        scope = str(arguments.get("scope") or "places")
        now = int(time.time() * 1000)
        allowed = {key: arguments[key] for key in ("name", "category", "city", "country", "address", "note", "rating", "lat", "lon") if arguments.get(key) is not None}
        if action == "update":
            item_id = str(arguments.get("item_id") or "")
            if not item_id:
                return {"updated": False, "clarificationRequired": True, "message": "Falta el ID del lugar."}
            write_started = time.perf_counter(); await self.client.patch_data(f"world/{scope}/{item_id}", {**allowed, "updatedAt": now}); write_ms = (time.perf_counter() - write_started) * 1000
            readback_started = time.perf_counter(); persisted = await self.client.data("world") or {}; readback_ms = (time.perf_counter() - readback_started) * 1000
            saved = (persisted.get(scope) or {}).get(item_id)
            verified = bool(saved) and all(saved.get(key) == value for key, value in allowed.items())
            return {"updated": verified, "verified": verified, "id": item_id, "item": saved, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}
        if not allowed.get("name") and not allowed.get("address"):
            return {"created": False, "clarificationRequired": True, "message": "¿Qué lugar debo guardar?"}
        item_id = f"jarvis_{uuid4()}"
        item = {"id": item_id, "kind": scope, **allowed, "createdAt": now, "updatedAt": now}
        write_started = time.perf_counter(); await self.client.put_data(f"world/{scope}/{item_id}", item); write_ms = (time.perf_counter() - write_started) * 1000
        readback_started = time.perf_counter(); persisted = await self.client.data("world") or {}; readback_ms = (time.perf_counter() - readback_started) * 1000
        saved = (persisted.get(scope) or {}).get(item_id)
        verified = bool(saved)
        return {"created": verified, "verified": verified, "item": saved or item, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}

    async def notes_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        notes = await self.client.data("notes/notes") or {}
        rows = [{"id": key, **value} for key, value in notes.items() if isinstance(value, dict)]
        query = _norm(arguments.get("query"))
        if query:
            rows = [row for row in rows if query in _norm(f"{row.get('title')} {row.get('content')} {' '.join(row.get('tags') or [])}")]
        rows.sort(key=lambda row: int(row.get("updatedAt") or row.get("createdAt") or 0), reverse=True)
        result = {"items": rows[: min(50, int(arguments.get("limit") or 10))], "count": len(rows)}
        if arguments.get("pending_only"):
            pending = []
            for row in rows:
                for line in str(row.get("content") or "").splitlines():
                    match = re.match(r"^\s*-\s*\[\s\]\s*(.+?)\s*$", line)
                    if match:
                        pending.append({"noteId": row.get("id"), "title": row.get("title"), "item": match.group(1)})
            result["pendingItems"] = pending
            result["count"] = len(pending)
        return result

    async def notes_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time() * 1000)
        action = str(arguments.get("action") or "create")
        allowed = {key: arguments[key] for key in ("title", "content", "category", "folderId", "tags") if arguments.get(key) is not None}
        folders = await self.client.data("notes/folders") or {}
        folder_id = str(allowed.get("folderId") or "").strip()
        if not folder_id:
            folder_id = next((
                key for key, value in folders.items()
                if isinstance(value, dict) and str(value.get("name") or "").strip().casefold() == "jarvis"
            ), "")
        if not folder_id:
            folder_id = str(uuid4())
            await self.client.put_data(f"notes/folders/{folder_id}", {
                "name": "JARVIS", "color": "#00d4ff", "createdAt": now,
                "parentId": "", "isPrivate": False, "pin": "", "emoji": "📝",
                "category": "", "tags": [], "defaultNoteKind": "text",
            })
        allowed["folderId"] = folder_id
        if action == "update":
            note_id = str(arguments.get("note_id") or "")
            persisted_before = await self.client.data("notes/notes") or {}
            if not note_id and arguments.get("title"):
                wanted = _norm(arguments.get("title"))
                matches = [key for key, value in persisted_before.items() if isinstance(value, dict) and _norm(value.get("title")) == wanted]
                if len(matches) == 1:
                    note_id = matches[0]
            if not note_id:
                return {"updated": False, "clarificationRequired": True, "message": "Falta identificar la nota."}
            current_note = persisted_before.get(note_id) or {}
            if arguments.get("append_content"):
                existing = str(current_note.get("content") or "").rstrip()
                added = str(arguments.get("append_content") or "").strip()
                allowed["content"] = f"{existing}\n{added}".strip()
            if arguments.get("check_item"):
                wanted_item = _norm(arguments.get("check_item"))
                lines = str(current_note.get("content") or "").splitlines()
                changed = False
                for index, line in enumerate(lines):
                    match = re.match(r"^(\s*-\s*)\[\s\](\s*)(.+?)\s*$", line)
                    if match and wanted_item in _norm(match.group(3)):
                        lines[index] = f"{match.group(1)}[x]{match.group(2)}{match.group(3)}"
                        changed = True
                        break
                if not changed:
                    return {"updated": False, "verified": False, "message": "No encuentro ese elemento pendiente."}
                allowed["content"] = "\n".join(lines)
            write_started = time.perf_counter(); await self.client.patch_data(f"notes/notes/{note_id}", {**allowed, "updatedAt": now}); write_ms = (time.perf_counter() - write_started) * 1000
            readback_started = time.perf_counter()
            persisted = await self.client.data("notes/notes") or {}
            readback_ms = (time.perf_counter() - readback_started) * 1000
            saved = persisted.get(note_id)
            verified = bool(saved) and all(saved.get(key) == value for key, value in allowed.items())
            return {"updated": verified, "verified": verified, "id": note_id, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}
        note_id = str(uuid4())
        title = str(allowed.get("title") or "").strip()
        note = {
            "folderId": folder_id, "title": title, "name": title,
            "content": str(allowed.get("content") or "").strip(), "linkRefs": [],
            "code": "", "noteKind": "text", "codeLanguage": "general",
            "previewHtml": "", "type": "note", "url": "",
            "category": str(allowed.get("category") or ""), "tags": list(allowed.get("tags") or []),
            "imageUrl": "", "imagePath": "", "imageUpdatedAt": 0,
            "attachments": {"images": []}, "tagImageKey": "", "rating": None,
            "visitsCount": 0, "lastVisitedAt": 0, "location": {}, "person": {},
            "createdAt": now, "updatedAt": now,
        }
        write_started = time.perf_counter(); await self.client.put_data(f"notes/notes/{note_id}", note); write_ms = (time.perf_counter() - write_started) * 1000
        readback_started = time.perf_counter()
        persisted = await self.client.data("notes/notes") or {}
        readback_ms = (time.perf_counter() - readback_started) * 1000
        saved = persisted.get(note_id)
        verified = bool(saved)
        return {"created": verified, "verified": verified, "id": note_id, "note": saved or note, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}

    async def recipes_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        recipes = await self.client.data("recipes/items") or {}
        rows = [{"id": key, **value} for key, value in recipes.items() if isinstance(value, dict)]
        query = _norm(arguments.get("query"))
        if query:
            rows = [row for row in rows if query in _norm(f"{row.get('title')} {row.get('notes')} {' '.join(row.get('tags') or [])}")]
        rows.sort(key=lambda row: int(row.get("updatedAt") or row.get("createdAt") or 0), reverse=True)
        return {"items": rows[: min(30, int(arguments.get("limit") or 10))], "count": len(rows)}

    async def recipes_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time() * 1000)
        action = str(arguments.get("action") or "create")
        allowed = {key: arguments[key] for key in ("title", "notes", "meal", "servings", "ingredients", "steps", "tags") if arguments.get(key) is not None}
        if action == "update":
            recipe_id = str(arguments.get("recipe_id") or "")
            if not recipe_id:
                return {"updated": False, "clarificationRequired": True, "message": "Falta identificar la receta."}
            write_started = time.perf_counter(); await self.client.patch_data(f"recipes/items/{recipe_id}", {**allowed, "updatedAt": now}); write_ms = (time.perf_counter() - write_started) * 1000
            readback_started = time.perf_counter(); persisted = await self.client.data("recipes/items") or {}; readback_ms = (time.perf_counter() - readback_started) * 1000
            saved = persisted.get(recipe_id)
            verified = bool(saved) and all(saved.get(key) == value for key, value in allowed.items())
            return {"updated": verified, "verified": verified, "id": recipe_id, "recipe": saved, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}
        recipe_id = str(uuid4())
        recipe = {"id": recipe_id, "ingredients": [], "steps": [], **allowed, "createdAt": now, "updatedAt": now}
        write_started = time.perf_counter(); await self.client.put_data(f"recipes/items/{recipe_id}", recipe); write_ms = (time.perf_counter() - write_started) * 1000
        readback_started = time.perf_counter(); persisted = await self.client.data("recipes/items") or {}; readback_ms = (time.perf_counter() - readback_started) * 1000
        saved = persisted.get(recipe_id)
        verified = bool(saved)
        return {"created": verified, "verified": verified, "recipe": saved or recipe, "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)}}

    def _workouts(self, root: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [{"date": date, "id": key, **value} for date, values in (root.get("workouts") or {}).items() for key, value in values.items() if isinstance(value, dict)]
        return sorted(rows, key=lambda row: int(row.get("finishedAt") or row.get("startedAt") or 0), reverse=True)

    @staticmethod
    def _workout_summary(workout: dict[str, Any]) -> dict[str, Any]:
        exercises = []
        for exercise_id, exercise in (workout.get("exercises") or {}).items():
            completed = [item for item in exercise.get("sets", []) if item.get("done")]
            exercises.append({"id": exercise_id, "name": exercise.get("nameSnapshot"), "sets": completed})
        return {key: workout.get(key) for key in ("id", "date", "name", "startedAt", "finishedAt", "durationSec", "totalReps", "totalVolumeKg")} | {"exercises": exercises}

    @staticmethod
    def _habits(root: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": key, **value} for key, value in (root.get("habits") or {}).items() if isinstance(value, dict) and value.get("name") and not value.get("archived") and not value.get("system")]

    @staticmethod
    def _scheduled(habit: dict[str, Any], date: str) -> bool:
        schedule = habit.get("schedule") or {"type": "daily"}
        if schedule.get("type") == "daily":
            return True
        js_day = (datetime.fromisoformat(date).weekday() + 1) % 7
        return js_day in (schedule.get("days") or [])

    def _habit_status(self, root: dict[str, Any], habit: dict[str, Any], date: str) -> dict[str, Any]:
        habit_id = str(habit["id"])
        goal = str(habit.get("goal") or "check")
        if goal == "count":
            value = (root.get("habitCounts") or {}).get(habit_id, {}).get(date, 0)
        elif goal == "time":
            raw = (root.get("habitSessions") or {}).get(habit_id, {}).get(date, 0)
            value = raw.get("totalSec", 0) if isinstance(raw, dict) else raw
        else:
            value = bool((root.get("habitChecks") or {}).get(habit_id, {}).get(date))
        budget = habit.get("budget") if isinstance(habit.get("budget"), dict) else None
        target = float(budget.get("value") or 0) if budget else 0
        comparable_value = float(value or 0)
        if goal == "time" and budget and str(budget.get("metric") or "").lower() in {"minute", "minutes", "min"}:
            comparable_value /= 60
        completed = comparable_value >= target if target > 0 else bool(value)
        history = set()
        for store in ("habitChecks", "habitCounts", "habitSessions"):
            for day, entry in ((root.get(store) or {}).get(habit_id) or {}).items():
                number = entry.get("totalSec", 0) if isinstance(entry, dict) else entry
                if number:
                    history.add(day)
        last = max(history) if history else None
        cursor = datetime.fromisoformat(date).date()
        if date not in history:
            cursor -= timedelta(days=1)
        streak = 0
        while cursor.isoformat() in history:
            streak += 1
            cursor -= timedelta(days=1)
        return {
            "id": habit_id, "name": habit.get("name"), "goal": goal, "date": date, "value": value,
            "completed": completed, "progressPercent": round(min(100, comparable_value / target * 100), 1) if target > 0 else (100 if value else 0),
            "lastCompletedDate": last, "daysSince": (datetime.fromisoformat(date).date() - datetime.fromisoformat(last).date()).days if last else None,
            "streak": streak, "budget": budget, "scheduled": self._scheduled(habit, date),
        }

    @staticmethod
    def _accounts(root: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for key, value in (root.get("accounts") or {}).items():
            if not isinstance(value, dict) or value.get("active") is False:
                continue
            entries = value.get("entries") or value.get("daily") or {}
            latest_day = max(entries) if entries else None
            rows.append({"id": key, "name": value.get("name"), "currency": value.get("currency"), "balance": entries.get(latest_day, {}).get("value") if latest_day else None, "balanceDate": latest_day})
        return rows

    @staticmethod
    def _categories(root: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [{"id": key, "name": value.get("name") or key, "type": value.get("type")} for key, value in ((root.get("catalog") or {}).get("categories") or {}).items() if isinstance(value, dict)]
        known = {_norm(row["name"]) for row in rows}
        for tx in (root.get("transactions") or {}).values():
            name = str(tx.get("category") or "").strip()
            if name and _norm(name) not in known:
                rows.append({"id": tx.get("categoryId") or _norm(name), "name": name, "type": tx.get("type")}); known.add(_norm(name))
        return rows

    @staticmethod
    def _movements(root: dict[str, Any], arguments: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [{"id": key, **value} for key, value in (root.get("transactions") or {}).items() if isinstance(value, dict) and not value.get("deleted")]
        start, end = str(arguments.get("from_date") or ""), str(arguments.get("until_date") or "")
        category, kind = _norm(arguments.get("category")), str(arguments.get("type") or "")
        rows = [row for row in rows if (not start or str(row.get("date", "")) >= start) and (not end or str(row.get("date", "")) <= end) and (not category or category in _norm(row.get("category"))) and (not kind or row.get("type") == kind)]
        return sorted(rows, key=lambda row: (str(row.get("date") or ""), int(row.get("createdAt") or 0)), reverse=True)

    @staticmethod
    def _infer_finance(transactions: list[dict[str, Any]], description: str, kind: str) -> dict[str, Any]:
        words = [word for word in _norm(description).split() if len(word) >= 3]
        matches = [tx for tx in transactions if tx.get("type") == kind and any(word in _norm(json.dumps(tx, ensure_ascii=False)) for word in words)]
        if not matches:
            return {}
        def confident(field: str) -> Any:
            values = [tx.get(field) for tx in matches if tx.get(field)]
            if not values:
                return None
            winner = max(set(values), key=values.count)
            return winner if values.count(winner) / len(values) >= 0.7 else None
        return {"accountId": confident("accountId"), "category": confident("category")}


def register_domain_tools(registry: ToolRegistry, domains: BookShellDomains) -> None:
    registry.register(Tool("bookshell_gym_query", "Consulta gimnasio: última sesión, días sin entrenar, sesiones recientes o historial de un ejercicio/peso.", {"type": "object", "properties": {"mode": {"type": "string", "enum": ["last", "days_since", "recent", "exercise"]}, "exercise": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["mode"]}, domains.gym_query))
    registry.register(Tool("bookshell_gym_write", "Registra directamente una sesión de gimnasio clara o actualiza el nombre de una sesión identificada. No inventes fecha ni ID si el usuario no los dice. No borra sesiones.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "update"]}, "session_id": {"type": "string"}, "date": {"type": "string"}, "name": {"type": "string"}, "exercises": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "sets": {"type": "integer"}, "reps": {"type": "integer"}, "kg": {"type": "number"}}, "required": ["name"]}}}, "required": ["action"]}, domains.gym_write))
    registry.register(Tool("bookshell_habits_query", "Lista hábitos y consulta estado, última realización, días, racha, progreso o pendientes de una fecha.", {"type": "object", "properties": {"mode": {"type": "string", "enum": ["list", "status", "pending"]}, "name": {"type": "string"}, "date": {"type": "string"}}, "required": ["mode"]}, domains.habits_query))
    registry.register(Tool("bookshell_habits_mark", "Marca un hábito o actualiza su valor cuantitativo. Ejecuta directamente si la intención es clara; desmarcar requiere confirmed=true.", {"type": "object", "properties": {"name": {"type": "string"}, "date": {"type": "string"}, "completed": {"type": "boolean"}, "value": {"type": "number"}, "unit": {"type": "string", "enum": ["count", "minutes", "seconds"]}, "confirmed": {"type": "boolean"}}, "required": ["name"]}, domains.habits_mark))
    registry.register(Tool("bookshell_finance_query", "Consulta cuentas, saldos, categorías, movimientos, último gasto o totales de gastos/ingresos por periodo y categoría.", {"type": "object", "properties": {"mode": {"type": "string", "enum": ["accounts", "categories", "movements", "latest", "summary"]}, "type": {"type": "string", "enum": ["expense", "income", "transfer"]}, "category": {"type": "string"}, "period": {"type": "string", "enum": ["today", "week", "month"]}, "from_date": {"type": "string"}, "until_date": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["mode"]}, domains.finance_query))
    registry.register(Tool("bookshell_finance_create", "Crea gasto, ingreso o transferencia mediante la API idempotente de BookShell. Si cuenta/categoría no son inequívocas devuelve una única aclaración; no adivina movimientos ambiguos.", {"type": "object", "properties": {"type": {"type": "string", "enum": ["expense", "income", "transfer"]}, "amount": {"type": "number"}, "currency": {"type": "string"}, "description": {"type": "string"}, "category": {"type": "string"}, "account": {"type": "string"}, "from_account": {"type": "string"}, "to_account": {"type": "string"}, "date": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["type", "amount"]}, domains.finance_write))
    registry.register(Tool("bookshell_reminders_query", "Consulta/busca recordatorios por hoy, mañana, esta semana, próxima semana, fechas, texto, persona o tipo de evento.", {"type": "object", "properties": {"scope": {"type": "string", "enum": ["today", "tomorrow", "this_week", "next_week"]}, "query": {"type": "string"}, "person": {"type": "string"}, "event_type": {"type": "string"}, "temporal_scope": {"type": "string", "enum": ["today", "future", "past", "all"]}, "status": {"type": "string"}, "from": {"type": "string"}, "until": {"type": "string"}, "limit": {"type": "integer"}}}, domains.reminders_query))
    registry.register(Tool("bookshell_reminder_update", "Modifica, completa o cancela un recordatorio existente. Cancelar requiere confirmed=true; completar y reprogramar no.", {"type": "object", "properties": {"reminder_id": {"type": "string"}, "action": {"type": "string", "enum": ["update", "complete", "cancel"]}, "title": {"type": "string"}, "description": {"type": "string"}, "target_date": {"type": "string"}, "target_time": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["reminder_id", "action"]}, domains.reminder_update))
    registry.register(Tool("bookshell_world_query", "Busca lugares guardados, locales, geografía o estancias por nombre, ciudad, categoría o país, incluyendo valoraciones.", {"type": "object", "properties": {"scope": {"type": "string", "enum": ["all", "saved", "places", "geography", "stays"]}, "query": {"type": "string"}, "city": {"type": "string"}, "category": {"type": "string"}, "country": {"type": "string"}, "limit": {"type": "integer"}}}, domains.world_query))
    registry.register(Tool("bookshell_world_write", "Guarda o actualiza un lugar/local en BookShell; no elimina datos.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "update"]}, "scope": {"type": "string", "enum": ["saved", "places", "geography"]}, "item_id": {"type": "string"}, "name": {"type": "string"}, "category": {"type": "string"}, "city": {"type": "string"}, "country": {"type": "string"}, "address": {"type": "string"}, "note": {"type": "string"}, "rating": {"type": "number"}, "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["action", "scope"]}, domains.world_write))
    registry.register(Tool("bookshell_notes_query", "Busca notas o elementos pendientes de una checklist.", {"type": "object", "properties": {"query": {"type": "string"}, "pending_only": {"type": "boolean"}, "limit": {"type": "integer"}}}, domains.notes_query))
    registry.register(Tool("bookshell_notes_write", "Crea o actualiza una nota visible en BookShell; admite checklists Markdown persistentes y no elimina notas.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "update"]}, "note_id": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "string"}, "append_content": {"type": "string"}, "check_item": {"type": "string"}, "category": {"type": "string"}, "folderId": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["action"]}, domains.notes_write))
    registry.register(Tool("bookshell_recipes_query", "Busca recetas y devuelve ingredientes, pasos y detalles reales.", {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}, domains.recipes_query))
    registry.register(Tool("bookshell_recipes_write", "Crea o actualiza una receta básica cuando ingredientes/pasos están claros; no elimina recetas.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "update"]}, "recipe_id": {"type": "string"}, "title": {"type": "string"}, "notes": {"type": "string"}, "meal": {"type": "string"}, "servings": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}}, "ingredients": {"type": "array", "items": {"type": "object"}}, "steps": {"type": "array", "items": {"type": "object"}}}, "required": ["action"]}, domains.recipes_write))
