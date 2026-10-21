class GatewayError(Exception):
    def __init__(self, code: str, message: str, status: int = 500) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.metadata = None
        super().__init__(code)


class ProviderError(GatewayError):
    def __init__(
        self, message: str = "Upstream provider failed", *, fallback_allowed: bool = True
    ) -> None:
        self.fallback_allowed = fallback_allowed
        super().__init__("provider_error", message, 502)


class ProviderTimeout(ProviderError):
    def __init__(self) -> None:
        GatewayError.__init__(self, "provider_timeout", "Upstream provider timed out", 504)


class ProviderRateLimit(ProviderError):
    def __init__(self) -> None:
        GatewayError.__init__(
            self, "provider_rate_limited", "Upstream rate limit exceeded", 429
        )
