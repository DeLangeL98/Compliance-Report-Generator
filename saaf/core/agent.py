"""
Compliance agent — orchestrates the mapper → prompt builder → Claude API → validator pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time

import anthropic
from pydantic import ValidationError

from config import Config
from saaf.core.mapper import FrameworkMapper, MappingResult
from saaf.core.models import AuditInput, ComplianceReport
from saaf.prompts.system_prompt import build_system_prompt, build_user_message

log = logging.getLogger("saaf.agent")


class ComplianceReportError(Exception):
    """Raised when the agent cannot produce a valid compliance report."""

    def __init__(self, message: str, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


class ComplianceAgent:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.client = anthropic.Anthropic(api_key=self.config.api_key)

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

        # Step 1: Deterministic framework mapping (no API call)
        mapping = FrameworkMapper(audit_input).map()
        log.info("Mapper: jurisdiction=%s  frameworks=%d  [%s]",
                 mapping.resolved_jurisdiction,
                 len(mapping.framework_matches),
                 ", ".join(m.key for m in mapping.framework_matches))

        # Step 2: Build prompts
        system_prompt = build_system_prompt(audit_input, mapping)
        user_message = build_user_message(audit_input, mapping)
        log.debug("Prompt sizes: system=%d chars  user=%d chars",
                  len(system_prompt), len(user_message))

        # Step 3: Call Claude with streaming + adaptive thinking
        raw_json = self._call_claude(system_prompt, user_message)

        # Step 4: Parse and validate
        report = self._parse_and_validate(raw_json, audit_input)
        log.info("Report ready: id=%s  risk=%s  frameworks=%d  regulations=%d",
                 report.report_id,
                 report.gap_risk_summary.overall_risk_rating,
                 len(report.framework_assessments),
                 len(report.mandatory_regulations))

        return report, mapping

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_claude(self, system_prompt: str, user_message: str) -> str:
        """Call Claude API with streaming and adaptive thinking. Retry once on failure."""
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            if attempt:
                log.warning("Retrying API call (attempt %d/%d)", attempt + 1, self.config.max_retries + 1)
            try:
                full_text = ""
                t_start = time.monotonic()
                thinking_tokens = 0

                log.info("Calling %s  max_tokens=%d  thinking=adaptive",
                         self.config.model, self.config.max_tokens)

                with self.client.messages.stream(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    thinking={"type": "adaptive"},
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                ) as stream:
                    current_block_type: str | None = None

                    for event in stream:
                        if event.type == "content_block_start":
                            current_block_type = getattr(event.content_block, "type", None)
                            if current_block_type == "thinking":
                                log.debug("Thinking block started")
                            elif current_block_type == "text":
                                log.debug("Text block started")

                        elif (
                            event.type == "content_block_delta"
                            and hasattr(event.delta, "type")
                        ):
                            if event.delta.type == "text_delta":
                                full_text += event.delta.text
                            elif event.delta.type == "thinking_delta":
                                thinking_tokens += len(event.delta.thinking)

                    final = stream.get_final_message()

                elapsed = time.monotonic() - t_start
                usage = final.usage
                log.info("API done in %.1fs  input=%d  output=%d  stop=%s",
                         elapsed, usage.input_tokens, usage.output_tokens, final.stop_reason)
                if thinking_tokens:
                    log.debug("Thinking block: ~%d chars", thinking_tokens)

                text_blocks = [b.text for b in final.content if b.type == "text"]
                if text_blocks:
                    return text_blocks[-1]
                return full_text

            except anthropic.APIStatusError as e:
                last_error = e
                log.error("API error %d: %s", e.status_code, e.message)
                if e.status_code < 500:
                    raise ComplianceReportError(
                        f"Claude API error ({e.status_code}): {e.message}"
                    ) from e
            except anthropic.APIConnectionError as e:
                last_error = e
                log.error("Connection error: %s", e)

        raise ComplianceReportError(
            f"Claude API failed after {self.config.max_retries + 1} attempts: {last_error}"
        )

    def _parse_and_validate(
        self, raw_json: str, audit_input: AuditInput
    ) -> ComplianceReport:
        """Extract JSON from Claude's response, parse, and validate."""
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
                f"Claude returned invalid JSON: {e}",
                raw_response=raw_json,
            ) from e

        log.debug("JSON parsed OK  keys=%s", list(data.keys()))

        if "audit_input" not in data or not data["audit_input"]:
            log.debug("audit_input missing from response — injecting from input")
            data["audit_input"] = audit_input.model_dump()

        try:
            report = ComplianceReport(**data)
        except ValidationError as e:
            log.error("Schema validation failed: %s", e)
            raise ComplianceReportError(
                f"Report failed schema validation: {e}",
                raw_response=raw_json,
            ) from e

        return report

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """
        Robustly extract the outermost JSON object from Claude's response.

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
