"""
Opt-in per-run audit trail.

When enabled, one JSON file named ``<report_id>.json`` is written per
successful run so a past run can be reconstructed from its report_id. The
record holds: inputs, mapped framework keys, the model provider, model name
and endpoint, call settings (max tokens, retries, timeout), the knowledge-base
version, call outcome (attempts, token usage, stop reason), SHA-256 of the
system+user prompt, UTC timestamps and the raw model response.

The endpoint is stored with any credentials, query string and fragment removed
(some gateways carry keys there); only scheme, host, port and path remain.

Redaction decision for ``company_name``: the company name may be sensitive,
so redaction is ON by default (``redact_company=True``). The stored inputs
then carry ``"[REDACTED]"`` instead of the name. The raw model response is
stored verbatim (it may echo the name), and the prompt hash is computed over
the unredacted prompt so it still identifies the exact prompt. Pass
``redact_company=False`` (CLI: ``--audit-trail-include-company``) to keep the
name; treat the directory as sensitive in that case.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

log = logging.getLogger("saaf.audit_trail")

REDACTED = "[REDACTED]"
RECORD_VERSION = 2


def sanitize_endpoint(endpoint: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return (endpoint_url, endpoint_host) with userinfo, query and fragment removed.

    Returns (None, None) when the value is not a usable http(s) URL.
    """
    if not isinstance(endpoint, str):
        return None, None
    try:
        parts = urlsplit(endpoint.strip())
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            return None, None
        host_port = f"[{host}]" if ":" in host else host  # IPv6 literal
        if parts.port:
            host_port = f"{host_port}:{parts.port}"
    except ValueError:
        return None, None
    return f"{parts.scheme}://{host_port}{parts.path}".rstrip("/"), host_port


def hash_prompt(system_prompt: str, user_message: str) -> str:
    """SHA-256 hex digest over the system and user prompts."""
    h = hashlib.sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_message.encode("utf-8"))
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_audit_record(
    directory: Path,
    *,
    report_id: str,
    inputs: Dict[str, Any],
    framework_keys: List[str],
    model: str,
    system_prompt: str,
    user_message: str,
    started_at: str,
    finished_at: str,
    raw_response: str,
    redact_company: bool = True,
    provider: Optional[str] = None,
    endpoint: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
    kb_version: Optional[str] = None,
    call: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write the record to ``<directory>/<report_id>.json`` and return its path."""
    # report_id is a UUID; reject anything that could escape the directory.
    if not report_id or Path(report_id).name != report_id:
        raise ValueError(f"Unsafe report_id: {report_id!r}")

    stored_inputs = dict(inputs)
    if redact_company and "company_name" in stored_inputs:
        stored_inputs["company_name"] = REDACTED

    endpoint_url, endpoint_host = sanitize_endpoint(endpoint)

    record = {
        "record_version": RECORD_VERSION,
        "report_id": report_id,
        "inputs": stored_inputs,
        "company_name_redacted": redact_company,
        "framework_keys": list(framework_keys),
        "provider": provider,
        "model": model,
        "endpoint_host": endpoint_host,
        "endpoint_url": endpoint_url,
        "settings": dict(settings or {}),
        "kb_version": kb_version,
        "call": dict(call or {}),
        "prompt_sha256": hash_prompt(system_prompt, user_message),
        "started_at": started_at,
        "finished_at": finished_at,
        "raw_response": raw_response,
    }

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    log.info("Audit trail written: %s", path)
    return path


class AuditTrail:
    """Settings holder; attach to a ComplianceAgent as ``agent.audit_trail``."""

    def __init__(self, directory: Path, redact_company: bool = True) -> None:
        self.directory = Path(directory)
        self.redact_company = redact_company

    def record(self, **kwargs: Any) -> Optional[Path]:
        """Write a record; log (never raise) on failure so a run is not lost."""
        try:
            return write_audit_record(
                self.directory, redact_company=self.redact_company, **kwargs
            )
        except (OSError, ValueError) as e:
            log.error("Failed to write audit trail: %s", e)
            return None
