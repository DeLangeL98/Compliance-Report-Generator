"""Base-URL validation shared by providers that accept a custom endpoint."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

log = logging.getLogger("saaf.llm")

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_base_url(base_url: str) -> str:
    """Return base_url stripped of trailing slashes; raise ValueError if unusable."""
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(
            f"Invalid base URL {base_url!r}: it must start with http:// or https:// "
            "and include a host."
        )
    if parts.username or parts.password:
        raise ValueError("Base URL must not embed credentials; use SAAF_API_KEY instead.")
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK_HOSTS:
        log.warning(
            "Base URL %s is plain http on a non-local host: the API key and "
            "engagement data are sent unencrypted.", parts.hostname,
        )
    return base_url.strip().rstrip("/")
