import base64
import json
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models import AudioResponse, ChatRequest, ChatResponse, FeedbackRequest, StatusResponse
from app.relay import CoreOfflineError, CoreRelay, CoreRequestError

VERSION = "0.2.0"
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.relay = CoreRelay(timeout=settings.core_timeout_seconds)
    yield


app = FastAPI(title="JARVIS Gateway", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def relay(request: Request) -> CoreRelay:
    return request.app.state.relay


def unavailable(exc: Exception) -> HTTPException:
    if isinstance(exc, CoreOfflineError):
        return HTTPException(status_code=503, detail="JARVIS Core is offline")
    return HTTPException(status_code=502, detail=str(exc))


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.get("/api/status", response_model=StatusResponse, tags=["system"])
async def api_status(request: Request) -> StatusResponse:
    active = relay(request)
    return StatusResponse(
        status="ready" if active.connected else "offline",
        gateway_version=VERSION,
        gateway_build_sha=settings.build_sha,
        web_build_sha=settings.build_sha,
        core_connected=active.connected,
        core=active.public_status,
    )


@app.post("/api/chat", response_model=ChatResponse, tags=["conversation"])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    try:
        result = await relay(request).request("chat", payload.model_dump())
        return ChatResponse.model_validate(result)
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.post("/api/chat/stream", tags=["conversation"])
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    async def events():
        try:
            async for event in relay(request).stream_request("chat_stream", payload.model_dump()):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except (CoreOfflineError, CoreRequestError) as exc:
            error = {"type": "error", "message": str(unavailable(exc).detail)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.post("/api/audio", response_model=AudioResponse, tags=["conversation"])
async def audio(
    request: Request,
    file: UploadFile = File(...),
    duration_ms: int | None = Form(default=None),
    speech_ms: int | None = Form(default=None),
    max_rms: float | None = Form(default=None),
    utterance_id: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    manual_finalize: bool = Form(default=False),
) -> AudioResponse:
    raw = await file.read(settings.max_audio_bytes + 1)
    if len(raw) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="Audio file is too large")
    if not raw:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    try:
        result = await relay(request).request(
            "audio",
            {
                "data": base64.b64encode(raw).decode("ascii"),
                "content_type": file.content_type or "audio/webm",
                "duration_ms": duration_ms,
                "speech_ms": speech_ms,
                "max_rms": max_rms,
                "utterance_id": utterance_id,
                "conversation_id": conversation_id,
                "manual_finalize": manual_finalize,
            },
        )
        return AudioResponse.model_validate(result)
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.post("/api/tts", tags=["conversation"])
async def tts(payload: ChatRequest, request: Request) -> Response:
    try:
        result = await relay(request).request("tts", {"text": payload.message, "language": payload.language, "turn_id": payload.turn_id})
        raw = base64.b64decode(str(result["data"]), validate=True)
        return Response(content=raw, media_type=str(result.get("content_type", "audio/mpeg")))
    except (CoreOfflineError, CoreRequestError, KeyError, ValueError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/memories", tags=["memory"])
async def memories(request: Request, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    try:
        result = await relay(request).request("memories", {"limit": limit})
        return list(result.get("items", []))
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/history", tags=["conversation"])
async def history(request: Request, limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
    try:
        result = await relay(request).request("history", {"limit": limit})
        return list(result.get("items", []))
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/stats", tags=["conversation"])
async def stats(request: Request) -> dict[str, int]:
    try:
        result = await relay(request).request("stats", {})
        return {
            "messages": int(result.get("messages", 0)),
            "positives": int(result.get("positives", 0)),
            "negatives": int(result.get("negatives", 0)),
        }
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.post("/api/feedback", status_code=201, tags=["conversation"])
async def feedback(payload: FeedbackRequest, request: Request) -> dict[str, Any]:
    try:
        return await relay(request).request("feedback", payload.model_dump())
    except (CoreOfflineError, CoreRequestError) as exc:
        raise unavailable(exc) from exc


@app.websocket("/internal/core/ws")
async def core_socket(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    expected = f"Bearer {settings.core_token}"
    if not secrets.compare_digest(authorization, expected):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid Core token")
        return
    await websocket.app.state.relay.serve(websocket)


@app.websocket("/ws")
async def browser_socket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    await websocket.accept()
    active: CoreRelay = websocket.app.state.relay
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "core_connected": active.connected})
                continue
            if message.get("type") != "chat" or not message.get("message"):
                await websocket.send_json({"type": "error", "message": "Unsupported message"})
                continue
            await websocket.send_json({"type": "state", "state": "thinking"})
            try:
                result = await active.request(
                    "chat",
                    {"message": str(message["message"]), "conversation_id": message.get("conversation_id")},
                )
                await websocket.send_json({"type": "response", **result})
            except (CoreOfflineError, CoreRequestError) as exc:
                await websocket.send_json({"type": "error", "message": str(unavailable(exc).detail)})
    except WebSocketDisconnect:
        return
