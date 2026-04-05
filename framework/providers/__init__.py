from framework.providers.base import LLMProvider, LLMResponse, ToolDef, CanonicalMessage


def get_provider(name: str = "anthropic", model: str | None = None) -> LLMProvider:
    """Factory: return the correct provider by name."""
    if name == "anthropic":
        from framework.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model) if model else AnthropicProvider()
    elif name == "openai":
        from framework.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model) if model else OpenAIProvider()
    elif name == "google":
        from framework.providers.google_provider import GoogleProvider
        return GoogleProvider(model=model) if model else GoogleProvider()
    else:
        raise ValueError(f"Unknown provider: {name!r}. Options: anthropic, openai, google")


__all__ = ["get_provider", "LLMProvider", "LLMResponse", "ToolDef", "CanonicalMessage"]
