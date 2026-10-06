"""Unit tests for the opt-in audit trail (no API needed)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saaf.core.audit_trail import REDACTED, AuditTrail, hash_prompt, utc_now


def _kwargs(report_id: str = "abc-123") -> dict:
    return dict(
        report_id=report_id,
        inputs={"company_name": "Secret Corp", "country": "US"},
        framework_keys=["sox", "coso"],
        model="test-model",
        system_prompt="sys",
        user_message="user",
        started_at=utc_now(),
        finished_at=utc_now(),
        raw_response='{"x": 1}',
    )


class TestAuditTrail(unittest.TestCase):
    def test_record_redacts_company_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = AuditTrail(Path(d) / "sub").record(**_kwargs())
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(path.name, "abc-123.json")
        self.assertEqual(data["inputs"]["company_name"], REDACTED)
        self.assertTrue(data["company_name_redacted"])
        self.assertEqual(data["inputs"]["country"], "US")
        self.assertEqual(data["framework_keys"], ["sox", "coso"])
        self.assertEqual(data["model"], "test-model")
        self.assertEqual(data["raw_response"], '{"x": 1}')
        self.assertEqual(data["prompt_sha256"], hash_prompt("sys", "user"))

    def test_company_kept_when_opted_in(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = AuditTrail(Path(d), redact_company=False).record(**_kwargs())
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["inputs"]["company_name"], "Secret Corp")

    def test_prompt_hash_separates_parts(self) -> None:
        self.assertNotEqual(hash_prompt("ab", "c"), hash_prompt("a", "bc"))

    def test_unsafe_report_id_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(AuditTrail(Path(d)).record(**_kwargs("../evil")))
            self.assertEqual(list(Path(d).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
