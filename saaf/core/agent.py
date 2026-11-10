"""
Compliance agent — orchestrates the mapper → prompt builder → LLM API → validator pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict
from typing import Optional

from pydantic import ValidationError

from config import Config
from saaf.core.audit_trail import AuditTrail, sanitize_endpoint, utc_now
from saaf.core.llm import LLMError, create_client
from saaf.core.mapper import FrameworkMapper, FrameworkMatch, MappingResult
from saaf.core.models import DISCLAIMER, AuditInput, ComplianceReport, ReferenceCheck
from saaf.core.reference_check import UNVERIFIED_NOTE, check_references
from saaf.knowledge.frameworks import KB_VERSION
from saaf.knowledge.regulations import jurisdiction_warning
from saaf.prompts.system_prompt import build_system_prompt, build_user_message

log = logging.getLogger("saaf.agent")


class ComplianceReportError(Exception):
    """Raised when the agent cannot produce a valid compliance report."""

    def __init__(self, message: str, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


def _normalise_name(name: str) -> str:
    """Case-insensitive, punctuation- and whitespace-insensitive comparison form."""
    return re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()


def _name_aliases(match: FrameworkMatch) -> set[str]:
    """Names a mapped framework may legitimately appear under in the model output."""
    full = match.full_name
    raw = {full, match.key, match.key.replace("_", " ")}
    head = re.split(r"\s+[—–-]\s+", full)[0]
    raw.add(head)
    raw.add(re.sub(r"\s*\([^)]*\)", "", head))  # head without parentheticals
    for inner in re.findall(r"\(([^)]*)\)", full):  # abbreviations, e.g. (SOX)
        for token in inner.split("/"):
            token = token.strip()
            if " " not in token and sum(c.isupper() for c in token) >= 2 and len(token) >= 3:
                raw.add(token)
    for part in head.split(" / "):
        raw.add(re.sub(r"\s*\([^)]*\)", "", part))
    return {n for n in (_normalise_name(r) for r in raw) if n}


class ComplianceAgent:
    # Optional opt-in audit trail (see saaf/core/audit_trail.py); off by default.
    audit_trail: Optional[AuditTrail] = None

    # Outcome of the most recent model call (attempts, token usage, stop reason)
    _last_call: dict = {}

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.client = create_client(self.config)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, audit_input: AuditInput) -> tuple[ComplianceReport, MappingResult]:
        """
        Run the full compliance analysis pipeline.

        Returns (ComplianceReport, MappingResult) so callers can access
        both the report and the intermediate mapping data.
        """
        log.info("Starting audit: %s | %s | %s | %s | %s",
                 audit_input.company_name, audit_input.industry,
                 audit_input.country, audit_input.listed_status, audit_input.audit_topic)

        log.info("Knowledge base version: %s", KB_VERSION)

        # Step 1: Deterministic framework mapping (no API call)
        mapping = FrameworkMapper(audit_input).map()
        log.info("Mapper: jurisdiction=%s  frameworks=%d  [%s]",
                 mapping.resolved_jurisdiction,
                 len(mapping.framework_matches),
                 ", ".join(m.key for m in mapping.framework_matches))

        warning = jurisdiction_warning(audit_input.country)
        if warning:
            log.warning(warning)

        # Step 2: Build prompts
        system_prompt = build_system_prompt(audit_input, mapping)
        user_message = build_user_message(audit_input, mapping)
        log.debug("Prompt sizes: system=%d chars  user=%d chars",
                  len(system_prompt), len(user_message))

        # Step 3: Call the configured model
        started_at = utc_now()
        self._last_call = {}
        raw_json = self._call_llm(system_prompt, user_message)

        # Step 4: Parse and validate
        report = self._parse_and_validate(raw_json, audit_input)
        # Overwrite anything the model supplied: warnings are agent-generated only
        report.warnings = [warning] if warning else []

        # Step 5: Reject anything the deterministic mapping did not select
        self._check_grounding(report, mapping, raw_json)

        if self.audit_trail is not None:
            self.audit_trail.record(
                report_id=report.report_id,
                inputs=audit_input.model_dump(),
                framework_keys=[m.key for m in mapping.framework_matches],
                provider=self.config.provider,
                model=self.config.model,
                endpoint=getattr(self.client, "endpoint", None),
                settings={
                    "max_tokens": self.config.max_tokens,
                    "max_retries": self.config.max_retries,
                    "timeout_seconds": self.config.timeout_seconds,
                },
                kb_version=KB_VERSION,
                call=self._last_call,
                system_prompt=system_prompt,
                user_message=user_message,
                started_at=started_at,
                finished_at=utc_now(),
                raw_response=raw_json,
            )
        log.info("Report ready: id=%s  risk=%s  frameworks=%d  regulations=%d",
                 report.report_id,
                 report.gap_risk_summary.overall_risk_rating,
                 len(report.framework_assessments),
                 len(report.mandatory_regulations))

        # Step 5: Compare references with the official clause lists. This shows
        # that a cited clause exists, not what it says: every reference stays
        # "unverified" (labelled, with a heuristic confidence score).
        log.warning(UNVERIFIED_NOTE)
        # Overwrite anything the model supplied: reference checks are agent-generated only
        report.reference_checks = [
            ReferenceCheck(**asdict(r)) for r in check_references(report, mapping)
        ]
        for r in report.reference_checks:
            if r.check in ("identifier_not_found", "unmapped_framework"):
                log.warning("Suspect reference [%s %s]: %r (%s; confidence %.2f)",
                            r.location, r.field, r.reference, r.note, r.confidence)

        return report, mapping

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Call the configured model, retrying transient (5xx / connection) failures."""
        last_error: Optional[Exception] = None

        for attempt in range(self.config.max_retries + 1):
            if attempt:
                log.warning("Retrying API call (attempt %d/%d)", attempt + 1, self.config.max_retries + 1)

            _, endpoint_host = sanitize_endpoint(getattr(self.client, "endpoint", None))
            log.info("Calling %s (provider=%s host=%s)  max_tokens=%d",
                     self.config.model, self.config.provider, endpoint_host,
                     self.config.max_tokens)
            t_start = time.monotonic()
            try:
                response = self.client.complete(
                    system_prompt, user_message, self.config.max_tokens
                )
            except LLMError as e:
                last_error = e
                log.error("API error%s: %s",
                          f" {e.status_code}" if e.status_code else "", e)
                if not e.retryable:
                    status = f" ({e.status_code})" if e.status_code else ""
                    raise ComplianceReportError(f"LLM API error{status}: {e}") from e
                continue

            log.info("API done in %.1fs  input=%s  output=%s  stop=%s",
                     time.monotonic() - t_start, response.input_tokens,
                     response.output_tokens, response.stop_reason)
            self._last_call = {
                "attempts": attempt + 1,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "stop_reason": response.stop_reason,
            }
            return response.text

        raise ComplianceReportError(
            f"LLM API failed after {self.config.max_retries + 1} attempts: {last_error}"
        )

    def _parse_and_validate(
        self, raw_json: str, audit_input: AuditInput
    ) -> ComplianceReport:
        """Extract JSON from the model's response, parse, and validate."""
        log.debug("Raw response: %d chars", len(raw_json))
        cleaned = self._extract_json_object(raw_json)
        if len(cleaned) != len(raw_json):
            log.debug("Extracted JSON object: %d chars (trimmed %d)",
                      len(cleaned), len(raw_json) - len(cleaned))

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("JSON parse failed at char %d: %s", e.pos, e.msg)
            raise ComplianceReportError(
                f"Model returned invalid JSON: {e}",
                raw_response=raw_json,
            ) from e

        log.debug("JSON parsed OK  keys=%s", list(data.keys()))

        # Agent-owned: the report must describe the engagement actually requested
        trusted_input = audit_input.model_dump()
        supplied_input = data.get("audit_input")
        if supplied_input is not None and supplied_input != trusted_input:
            log.warning("Model supplied a different audit_input — ignoring and using the input")
        data["audit_input"] = trusted_input

        if "disclaimer" in data:
            log.warning("Model supplied a disclaimer — ignoring and using the standard text")

        # Agent-generated only; a model-supplied value must not reach validation
        if data.pop("reference_checks", None) is not None:
            log.warning("Model supplied reference_checks — ignoring; the agent computes them")

        try:
            report = ComplianceReport(**data)
        except ValidationError as e:
            log.error("Schema validation failed: %s", e)
            raise ComplianceReportError(
                f"Report failed schema validation: {e}",
                raw_response=raw_json,
            ) from e

        # Not model-controlled: always force the standard disclaimer.
        report.disclaimer = DISCLAIMER
        return report

    @staticmethod
    def _check_grounding(
        report: ComplianceReport, mapping: MappingResult, raw_json: str = ""
    ) -> None:
        """
        Reject any framework or regulation that is not in the deterministic mapping.

        Mandatory regulations are drawn from the same registry as frameworks
        (mapper regulation keys are framework keys), so both lists are checked
        against the mapped frameworks.
        """
        allowed = [_name_aliases(m) for m in mapping.framework_matches]
        names = [a.framework_name for a in report.framework_assessments]
        names += [r.regulation_name for r in report.mandatory_regulations]
        ungrounded = [
            n for n in names
            if not any(_normalise_name(n) in aliases for aliases in allowed)
        ]

        if ungrounded:
            log.error("Grounding check failed: not in mapping: %s", ungrounded)
            raise ComplianceReportError(
                "Report references frameworks/regulations outside the mapped set: "
                + ", ".join(repr(n) for n in ungrounded),
                raw_response=raw_json,
            )

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """
        Robustly extract the outermost JSON object from the model's response.

        Handles:
          - Clean JSON with no surrounding text
          - Markdown code fences (```json ... ```)
          - Preamble prose before the opening brace
          - Trailing prose after the closing brace
        """
        text = text.strip()

        # 1. Strip markdown fences first
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n?```\s*$", "", text).strip()

        # 2. Slice from the first '{' to the last '}', discarding any surrounding prose
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]

        # 3. Couldn't locate JSON object — return as-is and let json.loads report the error
        return text
