import asyncio
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "core"))

from jarvis_core.config import CoreSettings
from jarvis_core.integrations.bookshell import BookShellClient
from jarvis_core.services import JarvisServices


async def main() -> None:
    client = BookShellClient()
    today = datetime.now(ZoneInfo(client.timezone)).date().isoformat()

    async def reminders() -> list[dict]:
        payload = await client._request("GET", "/reminders", params={"from": today, "until": today, "limit": 100})
        return list(payload.get("reminders") or [])

    before = await reminders()
    before_ids = {str(item.get("id")) for item in before}
    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="jarvis-reminder-route-", ignore_cleanup_errors=True) as data_dir:
        services = JarvisServices(CoreSettings(data_dir=Path(data_dir)))
        chunks: list[str] = []

        async def collect(chunk: str) -> None:
            chunks.append(chunk)

        started = time.perf_counter()
        first = await services.chat_stream({
            "message": "Anota que hoy tengo clase de alemán.",
            "conversation_id": "real-reminder-routing", "turn_id": "real-reminder-routing-1",
        }, collect)
        timings["clarification_ms"] = round((time.perf_counter() - started) * 1000, 1)
        after_question = await reminders()
        if first["message"] != "¿A qué hora, señor?":
            raise RuntimeError(f"Expected hour clarification, got {first['message']!r}")
        if {str(item.get("id")) for item in after_question} != before_ids:
            raise RuntimeError("A reminder was created before the missing hour was supplied")

        started = time.perf_counter()
        second = await services.chat_stream({
            "message": "A las cinco y media.",
            "conversation_id": "real-reminder-routing", "turn_id": "real-reminder-routing-2",
        }, collect)
        timings["create_verify_ms"] = round((time.perf_counter() - started) * 1000, 1)
        after_create = await reminders()
        created = next((item for item in after_create if str(item.get("id")) not in before_ids), None)
        if second["message"] != "Recordatorio creado, señor." or not created:
            raise RuntimeError(f"Verified creation failed: response={second}, reminders={after_create}")
        if created.get("targetDate") != today or created.get("targetTime") != "17:30":
            raise RuntimeError(f"Persisted reminder has unexpected date/time: {created}")

        started = time.perf_counter()
        today_first = await services.chat_stream({
            "message": "¿Qué tengo hoy?",
            "conversation_id": "real-reminder-routing", "turn_id": "real-reminder-routing-3",
        }, collect)
        timings["today_first_ms"] = round((time.perf_counter() - started) * 1000, 1)
        started = time.perf_counter()
        today_second = await services.chat_stream({
            "message": "¿Qué tengo hoy?",
            "conversation_id": "real-reminder-routing", "turn_id": "real-reminder-routing-4",
        }, collect)
        timings["today_second_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if "clase de alemán" not in today_first["message"].casefold() or "clase de alemán" not in today_second["message"].casefold():
            raise RuntimeError(f"Fresh today query did not return the new reminder: {today_first}, {today_second}")

        await client._request("PATCH", f"/reminders/{created['id']}", json={"status": "cancelled"})
        after_cancel = await reminders()
        remaining = next((item for item in after_cancel if str(item.get("id")) == str(created["id"])), None)
        if remaining and remaining.get("status") != "cancelled":
            raise RuntimeError("Test reminder cancellation was not persisted")
        services.storage.close()

    print(json.dumps({
        "first_response": first["message"], "created_response": second["message"],
        "reminder_id": created["id"], "title": created.get("title"),
        "date": created.get("targetDate"), "time": created.get("targetTime"),
        "today_first": today_first["message"], "today_second": today_second["message"],
        "status_after_cleanup": remaining.get("status") if remaining else "absent",
        "timings": timings,
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
