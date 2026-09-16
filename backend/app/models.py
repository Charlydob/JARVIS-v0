from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    message: str
    provider: str
    conversation_id: str


class AudioResponse(BaseModel):
    transcript: str
    provider: str
    detail: str


class Memory(BaseModel):
    id: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = {}


class StatusResponse(BaseModel):
    status: str
    version: str
    providers: dict[str, str]
