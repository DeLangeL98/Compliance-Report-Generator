"""Tests for clause-list checking (issue #7), using small synthetic clause lists.

The synthetic lists keep these tests independent of the real data files; the
last class checks the shipped data files for structure and a few well-known
identifiers.
"""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace as NS
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from saaf.core.clause_check import parse_locators  # noqa: E402
from saaf.core.reference_check import (  # noqa: E402
    CONFIDENCE,
    check_references,
)
from saaf.knowledge.clauses import (  # noqa: E402
    CLAUSE_LISTS,
    GRANULARITY,
    ClauseList,
    Instrument,
    frameworks_named,
    instruments_named,
)


def _inst(code, ids):
    return Instrument(code, code, "test", "https://example.test", "2026-10-06", frozenset(ids))


def _cl(key, *instruments):
    return ClauseList(key, "article-paragraph", "test rationale", tuple(instruments))


LISTS = {
    "GDPR": _cl("GDPR", _inst("GDPR", [
        "art:5", "art:5(1)", "art:5(2)", "art:32", "art:32(1)", "art:32(2)", "art:32(3)",
        "art:32(4)", "art:33", "recital:83",
    ])),
    "UK_GDPR": _cl(
        "UK_GDPR",
        _inst("UK_GDPR", ["art:5", "art:32", "art:45a"]),
        _inst("DPA_2018", ["sec:170", "sec:170(1)", "sch:2"]),
    ),
    "MiFID_II": _cl(
        "MiFID_II",
        _inst("MiFID_II", ["art:27", "art:27(1)"]),
        _inst("MiFIR", ["art:26", "art:26(1)"]),
    ),
    "HIPAA": _cl("HIPAA", _inst("HIPAA_PART_164", [
        "cfr:164.312", "cfr:164.312(a)", "cfr:164.312(a)(1)", "cfr:164.312(a)(2)",
        "cfr:164.312(a)(2)(iv)", "cfr:164.308", "cfr:164.308(a)", "cfr:164.308(a)(1)", "cfr:164.308(a)(1)(ii)",
        "cfr:164.308(a)(1)(ii)(A)",
    ])),
    "NIST_800_53": _cl("NIST_800_53", _inst("SP800_53_R5", [
        "ctrl:AC-2", "ctrl:AC-2(1)", "ctrl:AC-2(2)",
    ])),
    "NIST_CSF": _cl("NIST_CSF", _inst("CSF_2_0", [
        "fn:GV", "cat:GV.OC", "sub:GV.OC-01", "sub:PR.AA-01",
    ])),
}

FULL_NAMES = {
    "GDPR": "General Data Protection Regulation (EU) 2016/679",
    "UK_GDPR": "UK GDPR & Data Protection Act 2018",
    "MiFID_II": "Markets in Financial Instruments Directive II (MiFID II / MiFIR)",
    "HIPAA": "Health Insurance Portability and Accountability Act (HIPAA)",
    "NIST_800_53": "NIST SP 800-53 Rev 5 — Security and Privacy Controls",
    "NIST_CSF": "NIST Cybersecurity Framework v2.0",
    "ISO_27001": "ISO/IEC 27001:2022 — Information Security Management",
}


def _mapping(*keys):
    return NS(framework_matches=[NS(key=k, full_name=FULL_NAMES[k]) for k in keys])


def _check_one(ref, parent, *mapped, field="requirement_source"):
    """Run check_references on a one-reference report; return the single result."""
    if field == "requirement_source":
        report = NS(
            framework_assessments=[NS(framework_name=parent, control_objectives=[
                NS(control_id="C-1", requirement_source=ref)])],
            mandatory_regulations=[],
        )
    else:
        report = NS(
            framework_assessments=[],
            mandatory_regulations=[NS(regulation_name=parent, applicable_sections=[ref])],
        )
    out = check_references(report, _mapping(*mapped), LISTS)
    assert len(out) == 1
    return out[0]


class TestParseLocators(unittest.TestCase):
    def locs(self, text):
        return [(l.kind, l.number, l.subs) for l in parse_locators(text)]

    def test_article_paragraph_and_point(self):
        self.assertEqual(self.locs("GDPR Art. 32(1)(b)"), [("art", "32", ("1", "b"))])

    def test_article_list_and_range(self):
        self.assertEqual([n for _, n, _ in self.locs("Articles 5, 6 and 32")], ["5", "6", "32"])
        self.assertEqual(len(self.locs("Arts. 12–22")), 11)

    def test_cfr_and_usc_and_bare(self):
        self.assertEqual(self.locs("45 CFR 164.312(a)(2)(iv)"), [("sec", "164.312", ("a", "2", "iv"))])
        self.assertEqual(self.locs("15 U.S.C. § 6801(b)"), [("sec", "6801", ("b",))])
        self.assertEqual(self.locs("§ 164.308(a)(1)(ii)(A)"), [("sec", "164.308", ("a", "1", "ii", "a"))])
        self.assertEqual(self.locs("164.312(a)")[0][:2], ("sec", "164.312"))

    def test_nist_ids(self):
        self.assertEqual(self.locs("AC-2 (1)"), [("ctrl", "AC-2", ("1",))])
        self.assertEqual(self.locs("PR.AA-01"), [("sub", "PR.AA-01", ())])

    def test_no_locator(self):
        self.assertEqual(self.locs("Security of processing"), [])


class TestNaming(unittest.TestCase):
    def test_uk_gdpr_is_not_gdpr(self):
        self.assertEqual(frameworks_named("UK GDPR Art. 5"), ("UK_GDPR",))
        self.assertEqual(frameworks_named("GDPR Art. 5"), ("GDPR",))
        self.assertEqual(frameworks_named("Data Protection Act 2018 s.170"), ("UK_GDPR",))

    def test_two_frameworks_named_does_not_crash(self):
        self.assertEqual(set(frameworks_named("GDPR Art. 5 and UK GDPR Art. 5")), {"GDPR", "UK_GDPR"})

    def test_instrument_qualifier(self):
        self.assertEqual(instruments_named("MiFID_II", "MiFIR Art. 26"), ("MiFIR",))
        self.assertEqual(instruments_named("MiFID_II", "MiFID II Art. 27"), ("MiFID_II",))
        self.assertEqual(instruments_named("MiFID_II", "Art. 27"), ())


class TestCheckReferences(unittest.TestCase):
    def test_existing_article_found_but_unverified(self):
        r = _check_one("GDPR Art. 32", "x", "GDPR")
        self.assertEqual(r.check, "identifier_found")
        self.assertEqual(r.status, "unverified")
        self.assertEqual(r.confidence, CONFIDENCE["identifier_found"])
        self.assertLess(r.confidence, 1.0)

    def test_all_confidences_below_one(self):
        self.assertTrue(all(0.0 <= c < 1.0 for c in CONFIDENCE.values()))

    def test_missing_article_not_found(self):
        r = _check_one("GDPR Art. 100", "x", "GDPR")
        self.assertEqual(r.check, "identifier_not_found")
        self.assertEqual(r.confidence, CONFIDENCE["identifier_not_found"])

    def test_missing_paragraph_where_siblings_listed(self):
        self.assertEqual(_check_one("GDPR Art. 32(7)", "x", "GDPR").check, "identifier_not_found")

    def test_point_below_listed_level_accepted_via_parent(self):
        r = _check_one("GDPR Art. 32(1)(b)", "x", "GDPR")
        self.assertEqual(r.check, "parent_identifier_found")
        self.assertEqual(r.matched_identifiers, ["art:32(1)"])

    def test_paragraph_on_article_without_listed_paragraphs_accepted_via_parent(self):
        self.assertEqual(_check_one("GDPR Art. 33(1)", "x", "GDPR").check, "parent_identifier_found")

    def test_bare_clause_uses_parent_framework(self):
        r = _check_one("Art. 32(1)", "General Data Protection Regulation", "GDPR",
                       field="applicable_sections")
        self.assertEqual(r.check, "identifier_found")

    def test_range_requires_every_article(self):
        self.assertEqual(_check_one("GDPR Arts. 32-34", "x", "GDPR").check, "identifier_not_found")

    def test_one_missing_of_several_fails(self):
        self.assertEqual(_check_one("GDPR Articles 5 and 99", "x", "GDPR").check,
                         "identifier_not_found")

    def test_recital(self):
        self.assertEqual(_check_one("GDPR Recital 83", "x", "GDPR").check, "identifier_found")
        self.assertEqual(_check_one("GDPR Recital 999", "x", "GDPR").check, "identifier_not_found")

    def test_uk_gdpr_article_and_dpa_section(self):
        self.assertEqual(_check_one("UK GDPR Art. 45A", "x", "UK_GDPR").check, "identifier_found")
        self.assertEqual(_check_one("DPA 2018 s.170", "x", "UK_GDPR").check, "identifier_found")
        self.assertEqual(_check_one("Data Protection Act 2018 section 170(1)", "x",
                                    "UK_GDPR").check, "identifier_found")

    def test_uk_gdpr_reference_not_matched_against_gdpr(self):
        # art:45a exists only in the UK list; naming "GDPR" must not borrow UK data
        r = _check_one("GDPR Art. 45A", "x", "GDPR", "UK_GDPR")
        self.assertEqual(r.check, "identifier_not_found")

    def test_covered_but_unmapped_framework(self):
        r = _check_one("GDPR Art. 5", "x", "NIST_CSF")
        self.assertEqual(r.check, "unmapped_framework")

    def test_framework_without_clause_list(self):
        r = _check_one("ISO 27001 A.8.3", "ISO/IEC 27001:2022", "ISO_27001")
        self.assertEqual(r.check, "framework_not_covered")
        self.assertEqual(r.status, "unverified")

    def test_no_framework_named_anywhere(self):
        self.assertEqual(_check_one("Clause 9.9", "Made Up Standard", "GDPR").check,
                         "unmapped_framework")

    def test_framework_named_without_locator(self):
        self.assertEqual(_check_one("GDPR security of processing", "x", "GDPR").check, "no_locator")

    def test_instrument_split_mifid_vs_mifir(self):
        self.assertEqual(_check_one("MiFIR Art. 26", "x", "MiFID_II").check, "identifier_found")
        self.assertEqual(_check_one("MiFID II Art. 26", "x", "MiFID_II").check, "identifier_not_found")
        self.assertEqual(_check_one("MiFID II Art. 27(1)", "x", "MiFID_II").check, "identifier_found")

    def test_hipaa_cfr_depth(self):
        self.assertEqual(_check_one("45 CFR 164.312(a)(2)(iv)", "x", "HIPAA").check, "identifier_found")
        self.assertEqual(_check_one("HIPAA 164.308(a)(1)(ii)(A)", "x", "HIPAA").check, "identifier_found")
        self.assertEqual(_check_one("HIPAA 164.312(a)(2)(v)", "x", "HIPAA").check, "identifier_not_found")
        self.assertEqual(_check_one("HIPAA 164.999", "x", "HIPAA").check, "identifier_not_found")

    def test_nist_800_53_enhancement(self):
        self.assertEqual(_check_one("NIST SP 800-53 AC-2(1)", "x", "NIST_800_53").check,
                         "identifier_found")
        self.assertEqual(_check_one("NIST SP 800-53 AC-2(9)", "x", "NIST_800_53").check,
                         "identifier_not_found")

    def test_csf_1_1_ids_not_found(self):
        self.assertEqual(_check_one("NIST CSF PR.AA-01", "x", "NIST_CSF").check, "identifier_found")
        self.assertEqual(_check_one("NIST CSF PR.AC-1", "x", "NIST_CSF").check, "no_locator")
        self.assertEqual(_check_one("NIST CSF PR.AC-01", "x", "NIST_CSF").check, "identifier_not_found")

    def test_article_reference_under_nist_csf_is_not_found(self):
        self.assertEqual(_check_one("NIST CSF Article 5", "x", "NIST_CSF").check,
                         "identifier_not_found")


class TestShippedClauseData(unittest.TestCase):
    """Structure checks on saaf/knowledge/clause_data/*.json."""

    def test_every_list_declares_granularity_and_rationale(self):
        for key, cl in CLAUSE_LISTS.items():
            with self.subTest(key=key):
                self.assertTrue(cl.granularity)
                self.assertGreater(len(cl.granularity_rationale), 40)
                self.assertIn(key, GRANULARITY)

    def test_every_list_has_provenance_and_identifiers(self):
        for key, cl in CLAUSE_LISTS.items():
            for inst in cl.instruments:
                with self.subTest(key=key, instrument=inst.code):
                    self.assertTrue(inst.source.startswith("https://"))
                    self.assertTrue(inst.version)
                    self.assertEqual(len(inst.retrieved_on), 10)
                    self.assertGreater(len(inst.identifiers), 5)

    def test_granularity_table_covers_only_known_frameworks(self):
        from saaf.knowledge.frameworks import FRAMEWORK_REGISTRY
        for key in GRANULARITY:
            self.assertIn(key, FRAMEWORK_REGISTRY)
        for key in CLAUSE_LISTS:
            self.assertIn(key, FRAMEWORK_REGISTRY)


if __name__ == "__main__":
    unittest.main()
