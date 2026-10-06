"""Tests for the finding-schema export (no API calls required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent.parent))

from saaf.output.findings import TITLE_MAX_LENGTH, report_to_findings

try:
    from saaf.core.models import ComplianceReport
except ImportError:  # pydantic not installed
    ComplianceReport = None  # type: ignore

# Mirrors outputs/schemas/finding-schema.json (SAAF-Project/SAAF-Project).
REQUIRED = ["id", "title", "risk_rating", "observation", "recommendation"]
ALLOWED = {
    "id", "title", "risk_rating", "control_objective", "observation",
    "root_cause", "impact", "recommendation", "management_response",
    "target_date", "owner", "status", "ai_assisted", "evidence_references",
}
RATINGS = {"High", "Medium", "Low", "Informational"}
STATUSES = {"Open", "In Progress", "Closed"}
LONG_GAP = "Long gap " + "x" * 150

DATA = {
    "audit_input": {"company_name": "Acme", "industry": "Healthcare",
                    "country": "US", "listed_status": "Private",
                    "audit_topic": "Cybersecurity"},
    "mandatory_regulations": [],
    "framework_assessments": [
        {"framework_name": "ISO 27001", "applicability_rationale": "r",
         "control_objectives": [
             {"control_id": "ISO-AC-01", "description": "d",
              "requirement_source": "A.8.3", "testing_approach": "t",
              "priority": "High"}],
         "key_gaps": ["No MFA", LONG_GAP, "No asset inventory"],
         "risk_rating": "Critical"},
        {"framework_name": "HIPAA", "applicability_rationale": "r",
         "control_objectives": [], "key_gaps": ["Stale BAAs"],
         "risk_rating": "Low"},
    ],
    "gap_risk_summary": {
        "overall_risk_rating": "High",
        "critical_gaps": ["No MFA"],
        "recommended_priority_actions": ["Enable MFA", "Inventory assets"],
        "estimated_remediation_effort": "Medium",
        "executive_summary": "s"},
}


def _check_schema(tc: unittest.TestCase, f: dict) -> None:
    for k in REQUIRED:
        tc.assertIn(k, f)
        tc.assertIsInstance(f[k], str)
        tc.assertTrue(f[k].strip())
    tc.assertTrue(set(f) <= ALLOWED)
    tc.assertRegex(f["id"], r"^F-[0-9]{2,4}$")
    tc.assertLessEqual(len(f["title"]), TITLE_MAX_LENGTH)
    tc.assertIn(f["risk_rating"], RATINGS)
    tc.assertIn(f.get("status", "Open"), STATUSES)
    tc.assertIsInstance(f.get("ai_assisted", False), bool)


def _stub_report() -> NS:
    d = DATA
    return NS(
        framework_assessments=[
            NS(framework_name=fw["framework_name"],
               risk_rating=fw["risk_rating"], key_gaps=fw["key_gaps"],
               control_objectives=[NS(**c) for c in fw["control_objectives"]])
            for fw in d["framework_assessments"]],
        gap_risk_summary=NS(**d["gap_risk_summary"]))


class FindingsExportTests(unittest.TestCase):
    def _assert_export(self, report) -> None:
        findings = report_to_findings(report)
        # critical gap + 3 unique framework gaps ("No MFA" deduplicated)
        self.assertEqual(len(findings), 4)
        for f in findings:
            _check_schema(self, f)
        self.assertEqual([f["id"] for f in findings],
                         ["F-01", "F-02", "F-03", "F-04"])
        self.assertEqual(findings[0]["risk_rating"], "High")
        self.assertIn("Enable MFA", findings[0]["recommendation"])
        self.assertEqual(findings[1]["risk_rating"], "High")  # Critical -> High
        self.assertIn("ISO-AC-01", findings[1]["recommendation"])
        self.assertEqual(findings[1]["control_objective"], "ISO 27001")
        self.assertTrue(findings[1]["title"].endswith("..."))
        self.assertEqual(findings[-1]["risk_rating"], "Low")
        self.assertIn("Inventory assets", findings[-1]["recommendation"])

    def test_stub_report(self) -> None:
        self._assert_export(_stub_report())

    @unittest.skipIf(ComplianceReport is None, "pydantic not installed")
    def test_pydantic_report(self) -> None:
        self._assert_export(ComplianceReport.model_validate(DATA))

    def test_no_actions_still_valid(self) -> None:
        r = _stub_report()
        r.gap_risk_summary.recommended_priority_actions = []
        for f in report_to_findings(r):
            _check_schema(self, f)

    def test_empty_report(self) -> None:
        r = _stub_report()
        r.framework_assessments = []
        r.gap_risk_summary.critical_gaps = []
        self.assertEqual(report_to_findings(r), [])


if __name__ == "__main__":
    unittest.main()
