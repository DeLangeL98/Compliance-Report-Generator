import os
from dataclasses import dataclass

from saaf.core.llm import PROVIDERS, validate_base_url

DEFAULT_PROVIDER = "anthropic"
_DEFAULT_MODELS = {"anthropic": "claude-opus-4-6"}
_PROVIDER_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@dataclass
class Config:
    """
    LLM settings. Each of provider / model / base_url / api_key resolves in order:
    explicit argument, then environment variable, then default.

      provider  SAAF_PROVIDER   "anthropic" (default) or "openai" (any OpenAI-compatible API)
      model     SAAF_MODEL      default claude-opus-4-6 for anthropic; required for openai
      base_url  SAAF_BASE_URL   custom API endpoint; empty = the provider's own endpoint
      api_key   SAAF_API_KEY, else ANTHROPIC_API_KEY / OPENAI_API_KEY for the provider
    """

    api_key: str = ""
    model: str = ""
    provider: str = ""
    base_url: str = ""
    max_tokens: int = 32000
    max_retries: int = 2
    timeout_seconds: int = 180

    def __post_init__(self):
        self.provider = (
            self.provider or os.environ.get("SAAF_PROVIDER") or DEFAULT_PROVIDER
        ).strip().lower()
        if self.provider not in PROVIDERS:
            raise EnvironmentError(
                f"Unknown provider {self.provider!r}. Choose from: {', '.join(PROVIDERS)}."
            )

        self.model = (
            self.model or os.environ.get("SAAF_MODEL") or _DEFAULT_MODELS.get(self.provider, "")
        ).strip()
        if not self.model:
            raise EnvironmentError(
                f"No model set for provider {self.provider!r}. "
                "Pass --model or set SAAF_MODEL."
            )

        self.base_url = (self.base_url or os.environ.get("SAAF_BASE_URL") or "").strip()
        if self.base_url:
            try:
                self.base_url = validate_base_url(self.base_url)
            except ValueError as e:
                raise EnvironmentError(str(e)) from e

        key_env = _PROVIDER_KEY_ENV[self.provider]
        self.api_key = self.api_key or os.environ.get("SAAF_API_KEY") or os.environ.get(key_env, "")
        # Local OpenAI-compatible servers (Ollama, vLLM, ...) often need no key
        needs_key = not (self.provider == "openai" and self.base_url)
        if needs_key and not self.api_key:
            raise EnvironmentError(
                f"{key_env} environment variable is not set (or set SAAF_API_KEY).\n"
                f"Set it with: export {key_env}=your-key-here"
            )
