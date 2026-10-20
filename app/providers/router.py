from app.core.config import ModelMapping, Settings
from app.domain.errors import GatewayError
from app.domain.schemas import ModelInfo
from app.providers.base import BaseLLMProvider


class ProviderRouter:
    def __init__(self, settings: Settings, providers: dict[str, BaseLLMProvider]) -> None:
        self.models = {m.model: m for m in settings.gateway_models if m.enabled}
        self.providers = providers

    def resolve(self, model: str) -> tuple[BaseLLMProvider, ModelMapping]:
        mapping = self.models.get(model)
        if not mapping:
            raise GatewayError("model_not_found", "Requested model is not enabled", 404)
        return self.providers[mapping.provider], mapping

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(model=m.model, provider=m.provider, simulated_stream=m.provider == "mock")
            for m in self.models.values()
        ]
