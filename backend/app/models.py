from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)
    conversation_id: str | None = None
    language: str | None = Field(default=None, min_length=2, max_length=16)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ChatResponse(BaseModel):
    message: str
    provider: str
    conversation_id: str
    message_id: str
    language: str | None = None


class AudioResponse(BaseModel):
    transcript: str
    language: str | None = None
    provider: str
    detail: str = "complete"


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal["good", "bad"]
    correction: str | None = Field(default=None, max_length=16_000)

    @model_validator(mode="after")
    def correction_required_for_bad_rating(self) -> "FeedbackRequest":
        if self.rating == "bad" and not (self.correction or "").strip():
            raise ValueError("A correction is required when rating a response as bad")
        return self


class StatusResponse(BaseModel):
    status: Literal["ready", "offline"]
    gateway_version: str
    core_connected: bool
    core: dict[str, Any] | None = None
