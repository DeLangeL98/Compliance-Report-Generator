"""
SAAF — BIO2 (Baseline Informatiebeveiliging Overheid 2) selection tests, no API calls.

BIO2 applies to Dutch government bodies only. The mapper resolves NL to the EU
jurisdiction group, so selection relies on a separate country-level key (issue #35).

Run with:
    python -m unittest tests.test_bio2 -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from saaf.core.mapper import FrameworkMapper
from saaf.core.models import AuditInput
from saaf.knowledge.frameworks import FRAMEWORK_REGISTRY
from saaf.knowledge.regulations import normalise_country, normalise_jurisdiction

# Every spelling of the Netherlands the agent should recognise (matching is case-insensitive)
DUTCH_SPELLINGS = ["Netherlands", "NL", "The Netherlands", "Nederland", "nederland "]
# BIO2 is an information security baseline: these are the topics it is selected for
SECURITY_TOPICS = ["Cybersecurity", "IT General Controls", "Vendor Management", "Business Continuity"]
NON_SECURITY_TOPICS = [
    "Data Privacy", "Financial Reporting", "Anti-Money Laundering",
    "ESG & Sustainability", "Operational Risk",
]


def _keys(country: str, industry: str, topic: str, listed_status: str = "Government") -> list:
    audit_input = AuditInput(
        company_name="Test Corp", industry=industry, country=country,
        listed_status=listed_status, audit_topic=topic,
    )
    return FrameworkMapper(audit_input).map().applicable_framework_keys


class TestBio2Selection(unittest.TestCase):

    def test_dutch_government_gets_bio2_on_security_topics(self):
        for country in DUTCH_SPELLINGS:
            for topic in SECURITY_TOPICS:
                with self.subTest(country=country, topic=topic):
                    self.assertIn("BIO2", _keys(country, "Government", topic))

    def test_non_dutch_government_does_not_get_bio2(self):
        # Germany is in the same EU group as the Netherlands: the group alone must not select BIO2
        for country in ["Germany", "France", "US", "UK", "Australia", "Singapore"]:
            with self.subTest(country=country):
                self.assertNotIn("BIO2", _keys(country, "Government", "Cybersecurity"))

    def test_dutch_non_government_does_not_get_bio2(self):
        for industry in ["Financial Services", "Healthcare", "Technology", "Energy"]:
            with self.subTest(industry=industry):
                self.assertNotIn("BIO2", _keys("Netherlands", industry, "Cybersecurity", "Private"))

    def test_dutch_government_non_security_topics_do_not_get_bio2(self):
        for topic in NON_SECURITY_TOPICS:
            with self.subTest(topic=topic):
                self.assertNotIn("BIO2", _keys("Netherlands", "Government", topic))

    def test_eu_frameworks_still_apply_to_dutch_government(self):
        # The country key adds to the EU group, it must never replace it
        keys = _keys("Netherlands", "Government", "Cybersecurity")
        for expected in ["GDPR", "NIS2", "ISO_27001"]:
            self.assertIn(expected, keys)

    def test_rationale_names_the_country_scope(self):
        audit_input = AuditInput(
            company_name="Test Corp", industry="Government", country="Netherlands",
            listed_status="Government", audit_topic="Cybersecurity",
        )
        result = FrameworkMapper(audit_input).map()
        bio2 = next(m for m in result.framework_matches if m.key == "BIO2")
        self.assertIn("jurisdiction 'NL'", bio2.rationale)
        self.assertEqual(result.resolved_jurisdiction, "EU")


class TestCountryKey(unittest.TestCase):

    def test_dutch_spellings_resolve_to_nl(self):
        for country in DUTCH_SPELLINGS:
            with self.subTest(country=country):
                self.assertEqual(normalise_country(country), "NL")

    def test_other_countries_have_no_country_key(self):
        for country in ["Germany", "US", "UK", "Belgium", "", "Atlantis"]:
            with self.subTest(country=country):
                self.assertIsNone(normalise_country(country))

    def test_netherlands_still_resolves_to_the_eu_group(self):
        for country in DUTCH_SPELLINGS:
            with self.subTest(country=country):
                self.assertEqual(normalise_jurisdiction(country), "EU")


class TestBio2Entry(unittest.TestCase):

    def setUp(self):
        self.entry = FRAMEWORK_REGISTRY["BIO2"]

    def test_restricted_to_dutch_government(self):
        self.assertEqual(self.entry["jurisdictions"], ["NL"])
        self.assertEqual(self.entry["industries"], ["Government"])
        self.assertEqual(sorted(self.entry["audit_topics"]), sorted(SECURITY_TOPICS))

    def test_source_and_review_date_are_recorded(self):
        self.assertIn("officielebekendmakingen.nl", self.entry["source"])
        date.fromisoformat(self.entry["last_reviewed"])  # raises if missing or malformed

    def test_description_cites_version_and_does_not_invent_measure_numbers(self):
        description = self.entry["description"]
        self.assertIn("v1.3", description)
        self.assertIn("Staatscourant 2026, 7416", description)
        self.assertIn("not part of the provided knowledge", description)

    def test_domains_cover_the_iso_27001_and_27002_structure(self):
        joined = " ".join(self.entry["domains"])
        for theme in ["Organisational", "People", "Physical", "Technological"]:
            self.assertIn(theme, joined)


if __name__ == "__main__":
    unittest.main()
