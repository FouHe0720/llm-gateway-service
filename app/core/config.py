from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    provider: Literal["mock", "openai", "local", "ollama"]
    upstream_model: str = Field(default="mock-echo", min_length=1, max_length=128)
    enabled: bool = True
    fallback_model: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    gateway_environment: Literal["development", "production"] = "development"
    gateway_auth_enabled: bool = True
    gateway_api_key: SecretStr | None = None
    gateway_models: list[ModelMapping] = Field(
        default_factory=lambda: [ModelMapping(model="mock-echo", provider="mock")]
    )
    mock_chunk_delay_seconds: float = Field(default=0.02, ge=0, le=5)
    openai_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_api_key: SecretStr | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_context_length: int = Field(default=1024, ge=256, le=4096)
    ollama_default_max_tokens: int = Field(default=128, ge=1, le=512)
    ollama_keep_alive: str = "2m"
    gateway_max_provider_attempts: int = Field(default=6, ge=1, le=12)
    gateway_cache_enabled: bool = False
    gateway_cache_ttl_seconds: float = Field(default=60, gt=0, le=3600)
    gateway_cache_max_entries: int = Field(default=128, ge=1, le=4096)
    gateway_cache_max_bytes: int = Field(default=2_097_152, ge=1024, le=16_777_216)
    gateway_task_routes: dict[str, str] = Field(default_factory=dict)
    upstream_connect_timeout_seconds: float = Field(default=3, gt=0, le=60)
    upstream_read_timeout_seconds: float = Field(default=20, gt=0, le=300)
    gateway_request_timeout_seconds: float = Field(default=60, gt=0, le=600)
    upstream_max_retries: int = Field(default=2, ge=0, le=5)
    upstream_retry_base_seconds: float = Field(default=0.2, ge=0, le=10)
    upstream_concurrency: int = Field(default=8, ge=1, le=100)
    upstream_max_response_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    gateway_rate_limit_requests: int = Field(default=60, ge=1, le=100_000)
    gateway_rate_limit_window_seconds: float = Field(default=60, gt=0, le=3600)
    gateway_max_body_bytes: int = Field(default=131_072, ge=1024, le=1_048_576)

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        enabled = [m for m in self.gateway_models if m.enabled]
        if not enabled or len({m.model for m in self.gateway_models}) != len(
            self.gateway_models
        ):
            raise ValueError("Configure at least one enabled model and unique model aliases")
        if self.gateway_auth_enabled:
            if not self.gateway_api_key or len(self.gateway_api_key.get_secret_value()) < 16:
                raise ValueError("GATEWAY_API_KEY must contain at least 16 characters")
        elif self.gateway_environment != "development" or any(
            m.provider != "mock" for m in enabled
        ):
            raise ValueError(
                "Disabling gateway authentication requires development + Mock only"
            )
        for provider in {m.provider for m in enabled} - {"mock"}:
            url = {
                "openai": self.openai_base_url,
                "local": self.local_base_url,
                "ollama": self.ollama_base_url,
            }[provider]
            parsed = urlsplit(url or "")
            _ = parsed.port  # Validate malformed/out-of-range ports at startup.
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Provider base URL must be HTTP(S), without credentials/query")
            if provider in {"local", "ollama"} and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("LocalProvider requires a localhost endpoint")
            if provider == "openai" and (
                not self.openai_api_key or not self.openai_api_key.get_secret_value()
            ):
                raise ValueError("Enabled OpenAI-compatible provider requires OPENAI_API_KEY")
        aliases = {m.model: m for m in enabled}
        for mapping in enabled:
            if mapping.fallback_model:
                target = aliases.get(mapping.fallback_model)
                if not target or target.model == mapping.model or target.fallback_model:
                    raise ValueError(
                        "Fallback must target an enabled, distinct, terminal model"
                    )
        if any(target not in aliases for target in self.gateway_task_routes.values()):
            raise ValueError("Task routes must target enabled model aliases")
        return self
