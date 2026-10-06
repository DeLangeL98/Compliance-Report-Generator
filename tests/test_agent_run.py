"""
SAAF — ComplianceAgent.run tests with a mocked Anthropic client (no API calls).

Run with:
    python -m unittest tests.test_agent_run -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from saaf.core.agent import ComplianceAgent, ComplianceReportError
from saaf.core.models import AuditInput, ComplianceReport
from config import Config


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


def _fake_stream(text: str) -> MagicMock:
    """Mimic the context manager returned by client.messages.stream()."""
    event = SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )
    final = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        stop_reason="end_turn",
    )
    stream = MagicMock()
    stream.__iter__.return_value = iter([event])
    stream.get_final_message.return_value = final
    cm = MagicMock()
    cm.__enter__.return_value = stream
    cm.__exit__.return_value = False
    return cm


def _status_error(status: int) -> anthropic.APIStatusError:
    # The SDK only reads status_code, headers and request off the response,
    # so a MagicMock avoids depending on the HTTP library the SDK uses.
    response = MagicMock(status_code=status)
    response.headers = {}
    return anthropic.APIStatusError(f"error {status}", response=response, body=None)


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=MagicMock())


class _AgentTestCase(unittest.TestCase):
    """Builds a ComplianceAgent whose Anthropic client is a mock."""

    def setUp(self):
        env = patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
        env.start()
        self.addCleanup(env.stop)
        client_cls = patch("saaf.core.agent.anthropic.Anthropic")
        self.client = client_cls.start().return_value
        self.addCleanup(client_cls.stop)
        self.agent = ComplianceAgent(Config())

    def _respond_with(self, text: str):
        self.client.messages.stream.side_effect = lambda **kw: _fake_stream(text)


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
        self.assertEqual(self.client.messages.stream.call_count, 1)

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
        self.client.messages.stream.side_effect = _status_error(400)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        self.assertIn("400", str(ctx.exception))
        self.assertEqual(self.client.messages.stream.call_count, 1)

    def test_5xx_retries_max_retries_then_fails(self):
        self.client.messages.stream.side_effect = _status_error(503)
        with self.assertRaises(ComplianceReportError) as ctx:
            self.agent.run(_make_input())
        expected = self.agent.config.max_retries + 1
        self.assertEqual(self.client.messages.stream.call_count, expected)
        self.assertIn(f"{expected} attempts", str(ctx.exception))

    def test_connection_error_retries_max_retries_then_fails(self):
        self.client.messages.stream.side_effect = _connection_error()
        with self.assertRaises(ComplianceReportError):
            self.agent.run(_make_input())
        self.assertEqual(
            self.client.messages.stream.call_count,
            self.agent.config.max_retries + 1,
        )

    def test_transient_5xx_then_success_returns_report(self):
        self.client.messages.stream.side_effect = [
            _status_error(500),
            _fake_stream(json.dumps(_report_dict())),
        ]
        report, _ = self.agent.run(_make_input())
        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(self.client.messages.stream.call_count, 2)


if __name__ == "__main__":
    unittest.main()
