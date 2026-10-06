"""Tests for the heuristic reference check, using synthetic report objects."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent.parent))

from saaf.core.reference_check import (  # noqa: E402
    UNVERIFIED_NOTE,
    find_suspect_references,
)


def _mapping(*pairs):
    return NS(framework_matches=[NS(key=k, full_name=n) for k, n in pairs])


def _report(frameworks=(), regulations=()):
    return NS(
        framework_assessments=[
            NS(framework_name=name, control_objectives=[
                NS(control_id=cid, requirement_source=src) for cid, src in ctrls
            ])
            for name, ctrls in frameworks
        ],
        mandatory_regulations=[
            NS(regulation_name=name, applicable_sections=secs)
            for name, secs in regulations
        ],
    )


ISO = ("ISO_27001", "ISO/IEC 27001:2022 — Information Security Management")
GDPR = ("GDPR", "General Data Protection Regulation (EU) 2016/679")
SOX = ("SOX", "Sarbanes-Oxley Act 2002 (SOX)")


class TestReferenceCheck(unittest.TestCase):
    def test_mapped_reference_passes(self):
        rep = _report([("Other", [("C-1", "ISO 27001 A.8.3"), ("C-2", "ISO/IEC 27001:2022 A.5.1")])])
        self.assertEqual(find_suspect_references(rep, _mapping(ISO)), [])

    def test_unmapped_framework_flagged(self):
        rep = _report([("Other", [("C-1", "PCI DSS 4.0 Req 3.5")])])
        out = find_suspect_references(rep, _mapping(ISO))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].location, "C-1")
        self.assertEqual(out[0].field, "requirement_source")

    def test_bare_clause_ok_when_parent_framework_mapped(self):
        rep = _report([("ISO/IEC 27001:2022", [("C-1", "A.8.3")])])
        self.assertEqual(find_suspect_references(rep, _mapping(ISO)), [])

    def test_bare_clause_flagged_when_parent_unmapped(self):
        rep = _report([("Made Up Standard", [("C-1", "Clause 9.9")])])
        self.assertEqual(len(find_suspect_references(rep, _mapping(ISO))), 1)

    def test_regulation_sections(self):
        rep = _report(regulations=[
            ("Mystery Act", ["Section 12", "GDPR Art. 32"]),
            ("GDPR", ["Article 32", "Article 33"]),
            ("SOX", ["Section 404"]),
        ])
        out = find_suspect_references(rep, _mapping(GDPR, SOX))
        self.assertEqual([s.reference for s in out], ["Section 12"])
        self.assertEqual(out[0].field, "applicable_sections")

    def test_parenthetical_alias(self):
        rep = _report([("Other", [("C-1", "SOX 404")])])
        self.assertEqual(find_suspect_references(rep, _mapping(SOX)), [])

    def test_note_does_not_claim_verification(self):
        self.assertIn("NOT been verified", UNVERIFIED_NOTE)


if __name__ == "__main__":
    unittest.main()
