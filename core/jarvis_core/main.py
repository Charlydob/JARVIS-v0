import asyncio
import json
import logging
import signal
import socket
from contextlib import suppress
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices

LOGGER = logging.getLogger("jarvis-core")
INSTANCE_LOCK_PORT = 47651


class CompactConsoleFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name in {"httpx", "httpcore", "httpcore.http11", "httpcore.connection"} and record.levelno < logging.WARNING:
            return False
        # Tool completion lines already carry total duration and verification;
        # keep the detailed timing stages in core.log rather than duplicating them in PowerShell.
        if record.name == "jarvis-core.performance" and record.levelno < logging.WARNING:
            return False
        return True


def configure_logging(settings: CoreSettings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(settings.data_dir) / "core.log"
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s | %(message)s", datefmt="%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(CompactConsoleFilter())
    logfile = logging.FileHandler(log_path, encoding="utf-8")
    logfile.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=settings.log_level, handlers=[console, logfile], force=True)


def acquire_instance_lock() -> socket.socket:
    instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        instance_lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    instance_lock.bind(("127.0.0.1", INSTANCE_LOCK_PORT))
    instance_lock.listen(1)
    return instance_lock


async def send_json(socket: ClientConnection, lock: asyncio.Lock, payload: dict[str, Any]) -> None:
    async with lock:
        await socket.send(json.dumps(payload, ensure_ascii=False))


async def handle_request(
    socket: ClientConnection,
    lock: asyncio.Lock,
    services: JarvisServices,
    message: dict[str, Any],
) -> None:
    request_id = str(message.get("id", ""))
    try:
        action = str(message.get("action", ""))
        payload = dict(message.get("payload") or {})
        if action == "chat_stream":
            sequence = 0
            async def emit_chunk(chunk: str) -> None:
                nonlocal sequence
                sequence += 1
                turn_id = str(payload.get("turn_id") or request_id)
                await send_json(socket, lock, {
                    "type": "chunk", "id": request_id, "content": chunk,
                    "turn_id": turn_id, "event_id": f"{turn_id}:chunk:{sequence}",
                })

            result = await services.chat_stream(payload, emit_chunk)
        else:
            result = await services.dispatch(action, payload)
        response = {"type": "result", "id": request_id, "event_id": f"{payload.get('turn_id') or request_id}:result", "ok": True, "result": result}
    except Exception as exc:
        LOGGER.exception("Core request failed: %s", message.get("action"))
        response = {"type": "result", "id": request_id, "ok": False, "error": str(exc)}
    await send_json(socket, lock, response)


async def heartbeat(socket: ClientConnection, lock: asyncio.Lock, services: JarvisServices) -> None:
    count = 0
    while True:
        await asyncio.sleep(20)
        count += 1
        if count % 15 == 0:
            await services.ollama.warm()
        await send_json(socket, lock, {"type": "heartbeat", "metadata": await services.status()})


async def connected_session(settings: CoreSettings, services: JarvisServices) -> None:
    headers = {"Authorization": f"Bearer {settings.core_token}"}
    async with connect(
        settings.gateway_ws_url,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=20,
        max_size=32 * 1024 * 1024,
    ) as socket:
        LOGGER.info("Connected securely to gateway")
        lock = asyncio.Lock()
        await send_json(socket, lock, {"type": "hello", "metadata": await services.status()})
        asyncio.create_task(services.ollama.warm())
        heartbeat_task = asyncio.create_task(heartbeat(socket, lock, services))
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for raw in socket:
                message = json.loads(raw)
                if message.get("type") != "request":
                    continue
                task = asyncio.create_task(handle_request(socket, lock, services, message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            for task in tasks:
                task.cancel()


async def run() -> None:
    settings = CoreSettings()
    configure_logging(settings)
    if settings.core_token == "development-only-change-me" and settings.gateway_ws_url.startswith("wss://"):
        raise RuntimeError("Set a strong JARVIS_CORE_TOKEN before connecting to production")

    services = JarvisServices(settings)
    delay = 1
    while True:
        try:
            await connected_session(settings, services)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Gateway unavailable (%s); reconnecting in %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, settings.reconnect_max_seconds)


def main() -> None:
    try:
        instance_lock = acquire_instance_lock()
    except OSError:
        logging.basicConfig(level=logging.INFO)
        LOGGER.warning("Another JARVIS Core instance is already running; exiting")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(run())
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        if hasattr(signal, signal_name.name):
            with suppress(NotImplementedError):
                loop.add_signal_handler(signal_name, task.cancel)
    try:
        loop.run_until_complete(task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop.close()
        instance_lock.close()


if __name__ == "__main__":
    main()
