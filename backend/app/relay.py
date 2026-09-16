import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect


class CoreOfflineError(RuntimeError):
    pass


class CoreRequestError(RuntimeError):
    pass


class CoreRelay:
    """Owns the Core connection and multiplexes browser requests over it."""

    def __init__(self, timeout: float = 180.0) -> None:
        self.timeout = timeout
        self._socket: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self._connection_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._metadata: dict[str, Any] | None = None
        self._last_seen: datetime | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def public_status(self) -> dict[str, Any] | None:
        if not self.connected:
            return None
        metadata = dict(self._metadata or {})
        metadata["last_seen"] = self._last_seen.isoformat() if self._last_seen else None
        return metadata

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._connection_lock:
            previous = self._socket
            self._socket = websocket
            self._metadata = None
            self._last_seen = datetime.now(UTC)
            if previous is not None:
                with suppress(Exception):
                    await previous.close(code=1012, reason="A newer Core connected")

        try:
            await websocket.send_json({"type": "hello_ack"})
            while True:
                message = await websocket.receive_json()
                self._last_seen = datetime.now(UTC)
                message_type = message.get("type")
                if message_type in {"hello", "heartbeat"}:
                    metadata = message.get("metadata")
                    if isinstance(metadata, dict):
                        self._metadata = metadata
                    continue
                if message_type == "result":
                    request_id = str(message.get("id", ""))
                    future = self._pending.pop(request_id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
        except WebSocketDisconnect:
            pass
        finally:
            async with self._connection_lock:
                if self._socket is websocket:
                    self._socket = None
                    self._metadata = None
                    error = CoreOfflineError("JARVIS Core disconnected")
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(error)
                    self._pending.clear()

    async def request(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        socket = self._socket
        if socket is None:
            raise CoreOfflineError("JARVIS Core is offline")

        request_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            async with self._send_lock:
                if socket is not self._socket:
                    raise CoreOfflineError("JARVIS Core reconnected while sending")
                await socket.send_json({"type": "request", "id": request_id, "action": action, "payload": payload or {}})
            message = await asyncio.wait_for(future, timeout=self.timeout)
        except TimeoutError as exc:
            raise CoreRequestError(f"Core timed out while handling {action}") from exc
        finally:
            self._pending.pop(request_id, None)

        if not message.get("ok"):
            raise CoreRequestError(str(message.get("error", "Core request failed")))
        result = message.get("result")
        if not isinstance(result, dict):
            raise CoreRequestError("Core returned an invalid response")
        return result
