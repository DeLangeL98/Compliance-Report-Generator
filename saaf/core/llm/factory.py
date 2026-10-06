"""Build the client for ``config.provider``."""

from __future__ import annotations

from typing import Union

from saaf.core.llm.anthropic_client import AnthropicClient
from saaf.core.llm.openai_compatible import OpenAICompatibleClient

PROVIDERS = ("anthropic", "openai")


def create_client(config) -> Union[AnthropicClient, OpenAICompatibleClient]:
    """Build the client for config.provider (see config.Config)."""
    if config.provider == "anthropic":
        return AnthropicClient(
            api_key=config.api_key,
            model=config.model,
            timeout=config.timeout_seconds,
            base_url=config.base_url,
        )
    if config.provider == "openai":
        return OpenAICompatibleClient(
            api_key=config.api_key,
            model=config.model,
            timeout=config.timeout_seconds,
            base_url=config.base_url,
        )
    raise ValueError(f"Unknown provider {config.provider!r}; choose from {PROVIDERS}")
