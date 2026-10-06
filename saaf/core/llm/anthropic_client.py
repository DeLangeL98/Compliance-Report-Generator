"""Native Anthropic Messages API provider (the default)."""

from __future__ import annotations

import logging

from saaf.core.llm.base import LLMError, LLMResponse

log = logging.getLogger("saaf.llm")


class AnthropicClient:
    """Native Anthropic Messages API, streamed, with adaptive thinking."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        base_url: str = "",
    ) -> None:
        import anthropic  # lazy: only needed for this provider

        self._anthropic = anthropic
        self.model = model
        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**kwargs)
        # The SDK also honours ANTHROPIC_BASE_URL, so record what it will really call
        self.endpoint = str(self.client.base_url)

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        anthropic = self._anthropic
        try:
            full_text = ""
            thinking_chars = 0
            with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and hasattr(event.delta, "type")
                    ):
                        if event.delta.type == "text_delta":
                            full_text += event.delta.text
                        elif event.delta.type == "thinking_delta":
                            thinking_chars += len(event.delta.thinking)
                final = stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise LLMError(
                f"{e.message}", status_code=e.status_code, retryable=e.status_code >= 500
            ) from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Connection error: {e}", retryable=True) from e

        if thinking_chars:
            log.debug("Thinking block: ~%d chars", thinking_chars)
        text_blocks = [b.text for b in final.content if b.type == "text"]
        return LLMResponse(
            text=text_blocks[-1] if text_blocks else full_text,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            stop_reason=final.stop_reason,
        )
