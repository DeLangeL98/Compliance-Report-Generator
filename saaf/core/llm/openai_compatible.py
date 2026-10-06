"""Provider for any OpenAI-compatible ``/chat/completions`` endpoint (standard library only)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from saaf.core.llm.base import LLMError, LLMResponse
from saaf.core.llm.endpoint import validate_base_url

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: urllib would forward the Authorization header."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class OpenAICompatibleClient:
    """OpenAI-style ``POST {base_url}/chat/completions`` over the standard library."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        base_url: str = "",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        base = validate_base_url(base_url or DEFAULT_OPENAI_BASE_URL)
        # Accept either a base URL (…/v1) or the full endpoint URL
        self.url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        self.endpoint = self.url
        self._opener = urllib.request.build_opener(_NoRedirect)

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )

        try:
            with self._opener.open(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", errors="replace").strip()
            raise LLMError(
                f"HTTP {e.code} from {self.url}: {detail or e.reason}",
                status_code=e.code,
                retryable=e.code >= 500,
            ) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMError(f"Connection error to {self.url}: {e}", retryable=True) from e
        except (ValueError, UnicodeDecodeError) as e:
            raise LLMError(f"Endpoint returned a non-JSON response: {e}") from e

        try:
            choice = payload["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(
                "Endpoint response is not OpenAI chat-completions shaped "
                "(expected choices[0].message.content)."
            ) from e

        usage = payload.get("usage") or {}
        return LLMResponse(
            # Reasoning models may emit <think>…</think>; its braces would confuse JSON extraction
            text=_THINK_BLOCK.sub("", content).strip(),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            stop_reason=choice.get("finish_reason"),
        )
