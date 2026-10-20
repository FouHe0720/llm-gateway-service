from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16_000)

    @field_validator("content")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value  # Preserve prompt whitespace: it can matter to the model.


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128)
    messages: list[Message] = Field(min_length=1, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    top_p: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=1, le=8192, strict=True)

    @model_validator(mode="after")
    def bound_content(self) -> "ChatRequest":
        if sum(len(m.content) for m in self.messages) > 32_000:
            raise ValueError("Total message content exceeds 32000 characters")
        return self


class Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ChatResponse(BaseModel):
    answer: str
    model: str
    request_id: str
    usage: Usage | None = None
    latency_ms: float


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ModelInfo(BaseModel):
    model: str
    provider: str
    simulated_stream: bool


class ModelList(BaseModel):
    models: list[ModelInfo]
