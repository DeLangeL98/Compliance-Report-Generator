"""
Provider-neutral types shared by every LLM client.

The agent depends only on ``LLMClient.complete()`` and on these types, so a new
provider is one new module that implements the same method.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class LLMResponse:
    """Provider-neutral result of one completion."""

    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    stop_reason: Optional[str] = None


class LLMError(Exception):
    """A provider call failed. ``retryable`` is True for 5xx and connection errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class LLMClient(Protocol):
    """What the agent needs from a provider."""

    #: URL the client will call, for the audit trail (None if not applicable)
    endpoint: Optional[str]

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        ...
