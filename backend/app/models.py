from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16_000)
    conversation_id: str | None = None
    turn_id: str | None = Field(default=None, min_length=8, max_length=128)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ChatResponse(BaseModel):
    message: str
    provider: str
    conversation_id: str
    message_id: str
    language: str | None = None
    turn_id: str | None = None
    sources: list[dict[str, str]] | None = None


class AudioResponse(BaseModel):
    transcript: str
    language: str | None = None
    language_confidence: float | None = None
    provider: str
    detail: str = "complete"
    discard_reason: str | None = None
    utterance_id: str | None = None


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal["good", "bad"]
    correction: str | None = Field(default=None, max_length=16_000)
    reason: str | None = Field(default=None, max_length=64)
    reason_code: Literal[
        "incorrect_information", "should_have_used_tool", "wrong_tool",
        "action_not_executed", "ignored_context", "repeated_response",
        "too_long", "too_short", "wrong_tone", "other",
    ] | None = None
    comment: str | None = Field(default=None, max_length=16_000)
    expected_behavior: str | None = Field(default=None, max_length=16_000)

    @model_validator(mode="after")
    def detail_required_for_bad_rating(self) -> "FeedbackRequest":
        details = (self.reason_code, self.reason, self.correction, self.comment, self.expected_behavior)
        if self.rating == "bad" and not any((value or "").strip() for value in details):
            raise ValueError("A reason or correction is required when rating a response as bad")
        return self


class StatusResponse(BaseModel):
    status: Literal["ready", "offline"]
    gateway_version: str
    gateway_build_sha: str
    web_build_sha: str
    core_connected: bool
    core: dict[str, Any] | None = None
