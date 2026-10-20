from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelMapping(BaseModel):
    model: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    provider: Literal["mock", "openai", "local"]
    upstream_model: str = Field(default="mock-echo", min_length=1, max_length=128)
    enabled: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    gateway_environment: Literal["development", "production"] = "development"
    gateway_auth_enabled: bool = True
    gateway_api_key: SecretStr | None = None
    gateway_models: list[ModelMapping] = Field(
        default_factory=lambda: [ModelMapping(model="mock-echo", provider="mock")]
    )
    mock_chunk_delay_seconds: float = Field(default=0.02, ge=0, le=5)

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
        return self
