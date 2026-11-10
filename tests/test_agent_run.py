"""
SAAF — ComplianceAgent.run tests with a mocked LLM client (no API calls).

Run with:
    python -m unittest tests.test_agent_run -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from saaf.core.agent import ComplianceAgent, ComplianceReportError
from saaf.core.llm import LLMError, LLMResponse
from saaf.core.models import AuditInput, ComplianceReport
from tests import endpoints as E
from tests.test_llm import _completion, _Server

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input() -> AuditInput:
    return AuditInput(
        company_name="Test Corp",
        industry="Healthcare",
        country="US",
        listed_status="Private",
        audit_topic="Cybersecurity",
    )


def _report_dict() -> dict:
    """A minimal schema-valid model response."""
    return {
        "mandatory_regulations": [],
        "framework_assessments": [],
        "gap_risk_summary": {
            "overall_risk_rating": "High",
            "critical_gaps": ["Gap A"],
            "recommended_priority_actions": ["Action 1"],
            "estimated_remediation_effort": "Medium",
            "executive_summary": "Test summary.",
        },
    }


def _response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=20, stop_reason="end_turn")


def _status_error(status: int) -> LLMError:
    # Mirrors what the provider clients raise: only 5xx is retryable
    return LLMError(f"error {status}", status_code=status, retryable=status >= 500)


def _connection_error() -> LLMError:
    return LLMError("Connection error", retryable=True)


class _AgentTestCase(unittest.TestCase):
    """Builds a ComplianceAgent whose LLM client is a mock (provider-independent)."""

    def setUp(self):
        env = patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
        env.start()
        self.addCleanup(env.stop)
        factory = patch("saaf.core.agent.create_client")
        self.client = factory.start().return_value
        self.addCleanup(factory.stop)
        self.agent = ComplianceAgent(Config())

    def _respond_with(self, text: str):
        self.client.complete.side_effect = lambda *a, **kw: _response(text)


# ---------------------------------------------------------------------------
# Happy path and response extraction (CO-2 #1)
# ---------------------------------------------------------------------------

class TestAgentRunSuccess(_AgentTestCase):

    def test_happy_path_returns_report_and_mapping(self):
        self._respond_with(json.dumps(_report_dict()))
        report, mapping = self.agent.run(_make_input())
        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(report.gap_risk_summary.overall_risk_rating, "High")
        self.assertEqual(report.audit_input.company_name, "Test Corp")
        self.assertTrue(report.disclaimer)
        self.assertIn("HIPAA", [m.key for m in mapping.framework_matches])
        self.assertEqual(self.client.complete.call_count, 1)

    def test_markdown_fenced_json_is_extracted(self):
        self._respond_with("```json\n" + json.dumps(_report_dict()) + "\n```")
        report, _ = self.agent.run(_make_input())
        self.assertEqual(report.gap_risk_summary.critical_gaps, ["Gap A"])

    def test_prose_wrapped_json_is_extracted(self):
        self._respond_with(
            "Here is the report you asked for:\n"
            + json.dumps(_report_dict())
            + "\nLet me know if you need changes."
        )
        report, _ = self.agent.run(_make_input())
        self.assertEqual(report.gap_risk_summary.critical_gaps, ["Gap A"])


# ---------------------------------------------------------------------------
# audit_input is agent-owned (issue #43)
# ---------------------------------------------------------------------------

class TestAuditInputAgentOwned(_AgentTestCase):

    def test_different_audit_input_is_replaced_and_warned(self):
        forged = {
            "company_name": "Evil Corp",
            "industry": "Technology",
            "country": "Germany",
            "listed_status": "Public",
            "audit_topic": "Data Privacy",
        }
        self._respond_with(json.dumps({**_report_dict(), "audit_input": forged}))
        with self.assertLogs("saaf.agent", level="WARNING") as cm:
            report, _ = self.agent.run(_make_input())
        self.assertEqual(report.audit_input, _make_input())
        self.assertTrue(any("audit_input" in m for m in cm.output))
        self.assertFalse(any("Evil Corp" in m for m in cm.output))

    def test_invalid_audit_input_does_not_fail_validation(self):
        for invalid in ({"industry": "Aliens"}, "not an object", ["x"]):
            with self.subTest(invalid=invalid):
                self._respond_with(json.dumps({**_report_dict(), "audit_input": invalid}))
                report, _ = self.agent.run(_make_input())
                self.assertEqual(report.audit_input, _make_input())

    def test_exact_echo_is_not_warned_about(self):
        echo = _make_input().model_dump()
        self._respond_with(json.dumps({**_report_dict(), "audit_input": echo}))
        with self.assertLogs("saaf.agent", level="INFO") as cm:
            report, _ = self.agent.run(_make_input())
        self.assertEqual(report.audit_input, _make_input())
        self.assertFalse(any("audit_input" in m for m in cm.output))


# ---------------------------------------------------------------------------
# Audit trail records which provider / endpoint produced a report
# ---------------------------------------------------------------------------

class TestAgentAuditTrailMetadata(_AgentTestCase):

    def test_record_names_provider_endpoint_settings_and_call_outcome(self):
        import tempfile

        from saaf.core.audit_trail import AuditTrail
        self.client.endpoint = E.ENDPOINT_WITH_QUERY_SECRET
        self.client.complete.side_effect = [
            _status_error(503),
            _response(json.dumps(_report_dict())),
        ]
        with tempfile.TemporaryDirectory() as d:
            self.agent.audit_trail = AuditTrail(Path(d))
            report, _ = self.agent.run(_make_input())
            text = (Path(d) / f"{report.report_id}.json").read_text(encoding="utf-8")
        record = json.loads(text)

        self.assertEqual(record["provider"], self.agent.config.provider)
        self.assertEqual(record["model"], self.agent.config.model)
        self.assertEqual(record["endpoint_host"], E.HOSTED_HOST)
        self.assertNotIn("SECRET", text)
        self.assertEqual(record["settings"]["max_tokens"], self.agent.config.max_tokens)
        self.assertTrue(record["kb_version"])
        self.assertEqual(record["call"]["attempts"], 2)
        self.assertEqual(record["call"]["input_tokens"], 10)
        self.assertEqual(record["call"]["stop_reason"], "end_turn")


# ---------------------------------------------------------------------------
# Provider-independence: the whole agent against a custom OpenAI-compatible endpoint
# ---------------------------------------------------------------------------

class TestAgentCustomEndpoint(unittest.TestCase):

    def test_agent_runs_end_to_end_against_custom_endpoint(self):
        server = _Server(body=_completion(json.dumps(_report_dict())))
        self.addCleanup(server.close)
        with patch.dict("os.environ", {}, clear=True):
            config = Config(provider="openai", model="local-model", base_url=server.url + "/v1")
        report, _ = ComplianceAgent(config).run(_make_input())

        self.assertEqual(report.gap_risk_summary.critical_gaps, ["Gap A"])
        path, headers, body = server.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["model"], "local-model")
        self.assertNotIn("Authorization", headers)  # no key configured
        self.assertIn("Test Corp", body["messages"][1]["content"])


# ---------------------------------------------------------------------------
# Invalid model output (CO-2 #2, #3)
# ---------------------------------------------------------------------------

class TestAgentRunInvalidOutput(_AgentTestCase):

    def test_no_json_raises_with_raw_response(self):
        raw = "I'm sorry, I cannot produce that report."
        self._respond_with(raw)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        self.assertEqual(ctx.exception.raw_response, raw)

    def test_schema_invalid_json_raises_with_raw_response(self):
        bad = _report_dict()
        bad["gap_risk_summary"]["overall_risk_rating"] = "Catastrophic"
        raw = json.dumps(bad)
        self._respond_with(raw)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        self.assertEqual(ctx.exception.raw_response, raw)
        self.assertIn("schema validation", str(ctx.exception))


# ---------------------------------------------------------------------------
# API failures and retries (CO-2 #5)
# ---------------------------------------------------------------------------

class TestAgentRunApiErrors(_AgentTestCase):
    # The agent does not sleep between retries, so nothing needs patching.

    def test_4xx_fails_immediately_without_retry(self):
        self.client.complete.side_effect = _status_error(400)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        self.assertIn("400", str(ctx.exception))
        self.assertEqual(self.client.complete.call_count, 1)

    def test_5xx_retries_max_retries_then_fails(self):
        self.client.complete.side_effect = _status_error(503)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        expected = self.agent.config.max_retries + 1
        self.assertEqual(self.client.complete.call_count, expected)
        self.assertIn(f"{expected} attempts", str(ctx.exception))

    def test_connection_error_retries_max_retries_then_fails(self):
        self.client.complete.side_effect = _connection_error()
        with self.assertRaises(ComplianceReportError):
            self.agent.run(_make_input())
        self.assertEqual(
            self.client.complete.call_count,
            self.agent.config.max_retries + 1,
        )

    def test_transient_5xx_then_success_returns_report(self):
        self.client.complete.side_effect = [
            _status_error(500),
            _response(json.dumps(_report_dict())),
        ]
        report, _ = self.agent.run(_make_input())
        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(self.client.complete.call_count, 2)


if __name__ == "__main__":
    unittest.main()
