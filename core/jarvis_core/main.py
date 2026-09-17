import asyncio
import json
import logging
import signal
import socket
from contextlib import suppress
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices

LOGGER = logging.getLogger("jarvis-core")
INSTANCE_LOCK_PORT = 47651


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
        result = await services.dispatch(str(message.get("action", "")), dict(message.get("payload") or {}))
        response = {"type": "result", "id": request_id, "ok": True, "result": result}
    except Exception as exc:
        LOGGER.exception("Core request failed: %s", message.get("action"))
        response = {"type": "result", "id": request_id, "ok": False, "error": str(exc)}
    await send_json(socket, lock, response)


async def heartbeat(socket: ClientConnection, lock: asyncio.Lock, services: JarvisServices) -> None:
    while True:
        await asyncio.sleep(20)
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
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
