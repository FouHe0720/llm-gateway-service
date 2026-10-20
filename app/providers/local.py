from app.providers.openai_compatible import OpenAICompatibleProvider


class LocalProvider(OpenAICompatibleProvider):
    """Same HTTP protocol; Settings enforces a localhost URL. No model downloads."""
