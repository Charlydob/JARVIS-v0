from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.container import Providers, build_providers
from app.models import AudioResponse, ChatRequest, ChatResponse, Memory, StatusResponse

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.providers = build_providers(get_settings())
    yield


app = FastAPI(title="JARVIS Core API", version=VERSION, lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def providers(request: Request) -> Providers:
    return request.app.state.providers


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status", response_model=StatusResponse, tags=["system"])
async def status(request: Request) -> StatusResponse:
    active = providers(request)
    return StatusResponse(
        status="ready",
        version=VERSION,
        providers={"llm": active.llm.name, "stt": active.stt.name, "tts": active.tts.name, "memory": active.memory.name, "tools": active.tools.name},
    )


@app.post("/api/chat", response_model=ChatResponse, tags=["conversation"])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    conversation_id = payload.conversation_id or str(uuid4())
    active = providers(request)
    try:
        response = await active.llm.chat(payload.message, conversation_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The language provider is unavailable") from exc
    return ChatResponse(message=response, provider=active.llm.name, conversation_id=conversation_id)


@app.post("/api/audio", response_model=AudioResponse, tags=["conversation"])
async def audio(request: Request, file: UploadFile = File(...)) -> AudioResponse:
    active = providers(request)
    transcript = await active.stt.transcribe(await file.read(), file.content_type)
    return AudioResponse(transcript=transcript, provider=active.stt.name, detail="mock" if active.stt.name == "mock" else "complete")


@app.get("/api/memories", response_model=list[Memory], tags=["memory"])
async def memories(request: Request, limit: int = Query(50, ge=1, le=200)) -> list[Memory]:
    return await providers(request).memory.list(limit)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active: Providers = websocket.app.state.providers
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if message.get("type") != "chat" or not message.get("message"):
                await websocket.send_json({"type": "error", "message": "Unsupported message"})
                continue
            conversation_id = message.get("conversation_id") or str(uuid4())
            await websocket.send_json({"type": "state", "state": "thinking"})
            response = await active.llm.chat(str(message["message"]), conversation_id)
            await websocket.send_json({"type": "response", "message": response, "conversation_id": conversation_id, "provider": active.llm.name})
    except WebSocketDisconnect:
        return
