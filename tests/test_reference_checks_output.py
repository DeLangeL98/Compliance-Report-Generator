"""
Structured-output tests for reference checks (issue #7): the agent fills
`reference_checks`, ignores anything the model supplies, keeps the field out of
the model-facing schema, and the report renders the unverified label.

No API calls: the Anthropic client is mocked, as in test_agent_run.py.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from test_agent_run import _AgentTestCase, _make_input, _report_dict  # noqa: E402

from saaf.core.mapper import FrameworkMapper  # noqa: E402
from saaf.core.models import ComplianceReport  # noqa: E402
from saaf.output.formatter import render_references_note  # noqa: E402
from saaf.prompts.system_prompt import build_system_prompt  # noqa: E402


def _control(cid, source):
    return {
        "control_id": cid,
        "description": "d",
        "requirement_source": source,
        "testing_approach": "t",
        "priority": "High",
    }


def _response(**extra) -> dict:
    data = _report_dict()
    data["framework_assessments"] = [{
        "framework_name": "Health Insurance Portability and Accountability Act (HIPAA)",
        "applicability_rationale": "r",
        "control_objectives": [
            _control("H-1", "45 CFR 164.312(a)(2)(iv)"),   # exists
            _control("H-2", "45 CFR 164.312(a)(2)(v)"),    # not in the list
            _control("H-3", "164.308(a)(1)(ii)(A)"),       # bare clause, parent is HIPAA
            _control("H-4", "ISO 27001 A.8.3"),            # no clause list, not mapped here
        ],
        "key_gaps": ["g"],
        "risk_rating": "High",
    }]
    data.update(extra)
    return data


class TestAgentReferenceChecks(_AgentTestCase):

    def _run(self, **extra):
        self._respond_with(json.dumps(_response(**extra)))
        return self.agent.run(_make_input())[0]

    def test_every_reference_is_labelled_unverified_with_a_score(self):
        report = self._run()
        checks = {c.location: c for c in report.reference_checks}
        self.assertEqual(set(checks), {"H-1", "H-2", "H-3", "H-4"})
        for c in checks.values():
            self.assertEqual(c.status, "unverified")
            self.assertGreaterEqual(c.confidence, 0.0)
            self.assertLess(c.confidence, 1.0)
        self.assertEqual(checks["H-1"].check, "identifier_found")
        self.assertEqual(checks["H-2"].check, "identifier_not_found")
        self.assertEqual(checks["H-3"].check, "identifier_found")
        # a framework without a clause list is not checked against the parent's list
        self.assertEqual(checks["H-4"].check, "framework_not_covered")
        self.assertEqual(checks["H-4"].framework_key, "ISO_27001")
        self.assertGreater(checks["H-1"].confidence, checks["H-2"].confidence)

    def test_model_supplied_reference_checks_are_ignored(self):
        fake = [{"location": "H-2", "field": "requirement_source", "reference": "x",
                 "check": "identifier_found", "confidence": 0.99, "status": "unverified"}]
        report = self._run(reference_checks=fake)
        h2 = [c for c in report.reference_checks if c.location == "H-2"]
        self.assertEqual(len(h2), 1)
        self.assertEqual(h2[0].check, "identifier_not_found")

    def test_malformed_model_supplied_reference_checks_do_not_fail_validation(self):
        report = self._run(reference_checks="not a list")
        self.assertEqual(len(report.reference_checks), 4)

    def test_reference_checks_present_in_json_output(self):
        report = self._run()
        dumped = json.loads(report.model_dump_json())
        self.assertEqual(len(dumped["reference_checks"]), 4)
        self.assertEqual({c["status"] for c in dumped["reference_checks"]}, {"unverified"})


class TestSchemaHidesReferenceChecks(unittest.TestCase):

    def test_model_facing_schema_excludes_the_field(self):
        mapping = FrameworkMapper(_make_input()).map()
        prompt = build_system_prompt(_make_input(), mapping)
        self.assertNotIn("reference_checks", prompt)
        self.assertNotIn("ReferenceCheck", prompt)
        # sanity: the model itself does define the field
        self.assertIn("reference_checks", ComplianceReport.model_json_schema()["properties"])


class TestRendering(unittest.TestCase):

    def test_references_note_summarises_checks_and_flags_weak_ones(self):
        report = ComplianceReport(audit_input=_make_input(), **_response())
        mapping = FrameworkMapper(_make_input()).map()
        # rendering computes the checks itself if the agent has not filled them in
        buf = io.StringIO()
        render_references_note(report, mapping,
                               target=Console(file=buf, width=200, force_terminal=False))
        text = buf.getvalue()
        self.assertIn("unverified", text)
        self.assertIn("identifier_found", text)
        self.assertIn("identifier_not_found", text)
        self.assertIn("164.312(a)(2)(v)", text)  # listed as a reference to check first


if __name__ == "__main__":
    unittest.main()
