"""
Model-agnostic LLM client layer.

Providers (one module each):

  anthropic_client    Native Anthropic Messages API (streaming, adaptive thinking).
  openai_compatible   Any OpenAI-compatible ``/chat/completions`` endpoint: OpenAI,
                      Azure-style gateways, vLLM, Ollama, LiteLLM, LM Studio, ...

Both accept a custom ``base_url``. The openai provider uses only the standard
library; the Anthropic SDK is imported lazily and is only needed for the
anthropic provider. Everything callers need is re-exported here.
"""

from saaf.core.llm.anthropic_client import AnthropicClient
from saaf.core.llm.base import LLMClient, LLMError, LLMResponse
from saaf.core.llm.endpoint import validate_base_url
from saaf.core.llm.factory import PROVIDERS, create_client
from saaf.core.llm.openai_compatible import DEFAULT_OPENAI_BASE_URL, OpenAICompatibleClient

__all__ = [
    "AnthropicClient",
    "DEFAULT_OPENAI_BASE_URL",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "OpenAICompatibleClient",
    "PROVIDERS",
    "create_client",
    "validate_base_url",
]
