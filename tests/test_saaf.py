"""
SAAF — Test Suite (6 tests, no API calls required)

Run with:
    python -m pytest tests/ -v
or:
    python -m unittest tests.test_saaf -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from saaf.core.agent import ComplianceAgent, ComplianceReportError
from saaf.core.mapper import FrameworkMapper
from saaf.core.models import DISCLAIMER, AuditInput, ComplianceReport
from saaf.knowledge.frameworks import FRAMEWORK_REGISTRY, KB_VERSION
from saaf.knowledge.regulations import jurisdiction_warning, normalise_jurisdiction
from saaf.output import formatter
from saaf.prompts.system_prompt import build_system_prompt, build_user_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(**kwargs) -> AuditInput:
    """Build an AuditInput with sensible defaults, overridable via kwargs."""
    defaults = dict(
        company_name="Test Corp",
        industry="Healthcare",
        country="US",
        listed_status="Private",
        audit_topic="Cybersecurity",
    )
    defaults.update(kwargs)
    return AuditInput(**defaults)


# ---------------------------------------------------------------------------
# Test 1 — Jurisdiction normaliser
# ---------------------------------------------------------------------------

class TestJurisdictionNormaliser(unittest.TestCase):
    """Verify that country strings resolve to canonical jurisdiction keys."""

    def test_us_variants(self):
        for country in ["US", "USA", "United States", "united states of america"]:
            with self.subTest(country=country):
                self.assertEqual(normalise_jurisdiction(country), "US")

    def test_eu_member_states(self):
        for country in ["Germany", "DE", "France", "FR", "Ireland", "IE", "NL"]:
            with self.subTest(country=country):
                self.assertEqual(normalise_jurisdiction(country), "EU")

    def test_uk(self):
        for country in ["UK", "GB", "United Kingdom", "England"]:
            with self.subTest(country=country):
                self.assertEqual(normalise_jurisdiction(country), "UK")

    def test_australia(self):
        for country in ["AU", "AUS", "Australia"]:
            with self.subTest(country=country):
                self.assertEqual(normalise_jurisdiction(country), "AU")

    def test_singapore(self):
        self.assertEqual(normalise_jurisdiction("Singapore"), "SG")

    def test_unknown_returns_other(self):
        self.assertEqual(normalise_jurisdiction("Narnia"), "OTHER")
        self.assertEqual(normalise_jurisdiction("ZZ"), "OTHER")


# ---------------------------------------------------------------------------
# Test 2 — Framework mapper correctness
# ---------------------------------------------------------------------------

class TestFrameworkMapper(unittest.TestCase):
    """
    Verify the deterministic mapper selects the right frameworks for
    known input profiles without any API calls.
    """

    def _map(self, **kwargs):
        return FrameworkMapper(_make_input(**kwargs)).map()

    # --- US Healthcare Private + Cybersecurity ---
    def test_us_healthcare_includes_hipaa(self):
        result = self._map(industry="Healthcare", country="US",
                           listed_status="Private", audit_topic="Cybersecurity")
        keys = result.applicable_framework_keys
        self.assertIn("HIPAA", keys, "HIPAA must be selected for US Healthcare")

    def test_us_healthcare_includes_hitrust(self):
        result = self._map(industry="Healthcare", country="US",
                           listed_status="Private", audit_topic="Cybersecurity")
        self.assertIn("HITRUST_CSF", result.applicable_framework_keys)

    def test_us_healthcare_includes_nist_csf(self):
        result = self._map(industry="Healthcare", country="US",
                           listed_status="Private", audit_topic="Cybersecurity")
        self.assertIn("NIST_CSF", result.applicable_framework_keys)

    # --- EU Financial Services Public + Data Privacy ---
    def test_eu_finserv_includes_gdpr(self):
        result = self._map(industry="Financial Services", country="Germany",
                           listed_status="Public", audit_topic="Data Privacy")
        self.assertIn("GDPR", result.applicable_framework_keys,
                      "GDPR must be selected for EU entity")

    def test_eu_finserv_includes_dora(self):
        result = self._map(industry="Financial Services", country="France",
                           listed_status="Public", audit_topic="Cybersecurity")
        self.assertIn("DORA", result.applicable_framework_keys,
                      "DORA must be selected for EU Financial Services")

    def test_eu_public_includes_csrd(self):
        result = self._map(industry="Financial Services", country="Germany",
                           listed_status="Public", audit_topic="ESG & Sustainability")
        self.assertIn("CSRD_ESRS", result.applicable_framework_keys,
                      "CSRD must be selected for EU Public companies")

    # --- US Public Financial Services + Financial Reporting ---
    def test_us_public_finserv_includes_sox(self):
        result = self._map(industry="Financial Services", country="US",
                           listed_status="Public", audit_topic="Financial Reporting")
        self.assertIn("SOX", result.applicable_framework_keys,
                      "SOX must be selected for US Public companies")

    def test_us_private_excludes_sox(self):
        result = self._map(industry="Healthcare", country="US",
                           listed_status="Private", audit_topic="Financial Reporting")
        self.assertNotIn("SOX", result.applicable_framework_keys,
                         "SOX must NOT apply to Private companies")

    # --- US Energy + Cybersecurity ---
    def test_us_energy_includes_nerc_cip(self):
        result = self._map(industry="Energy", country="US",
                           listed_status="Private", audit_topic="Cybersecurity")
        self.assertIn("NERC_CIP", result.applicable_framework_keys)

    # --- Framework match objects have required fields ---
    def test_framework_matches_have_rationale(self):
        result = self._map(industry="Technology", country="US",
                           listed_status="Private", audit_topic="IT General Controls")
        for match in result.framework_matches:
            self.assertTrue(match.rationale, f"{match.key} has empty rationale")
            self.assertTrue(match.full_name, f"{match.key} has empty full_name")

    def test_resolved_jurisdiction_set(self):
        result = self._map(country="Singapore")
        self.assertEqual(result.resolved_jurisdiction, "SG")


# ---------------------------------------------------------------------------
# Test 3 — Pydantic model validation
# ---------------------------------------------------------------------------

class TestPydanticModels(unittest.TestCase):
    """Verify input and output schemas accept valid data and reject invalid data."""

    def test_valid_audit_input(self):
        ai = _make_input()
        self.assertEqual(ai.company_name, "Test Corp")
        self.assertEqual(ai.industry, "Healthcare")

    def test_invalid_industry_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            AuditInput(
                company_name="X",
                industry="Intergalactic Mining",   # not in Literal
                country="US",
                listed_status="Private",
                audit_topic="Cybersecurity",
            )

    def test_invalid_listed_status_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            AuditInput(
                company_name="X",
                industry="Healthcare",
                country="US",
                listed_status="Sovereign",          # not in Literal
                audit_topic="Cybersecurity",
            )

    def test_compliance_report_defaults(self):
        """ComplianceReport auto-populates report_id, generated_at, and disclaimer."""
        ai = _make_input()
        report = ComplianceReport(
            audit_input=ai,
            mandatory_regulations=[],
            framework_assessments=[],
            gap_risk_summary={
                "overall_risk_rating": "High",
                "critical_gaps": [],
                "recommended_priority_actions": [],
                "estimated_remediation_effort": "Medium",
                "executive_summary": "Test summary.",
            },
        )
        self.assertTrue(report.report_id)
        self.assertTrue(report.generated_at)
        self.assertTrue(report.disclaimer)

    def test_compliance_report_json_roundtrip(self):
        """A ComplianceReport survives a JSON serialise → deserialise cycle."""
        ai = _make_input()
        report = ComplianceReport(
            audit_input=ai,
            mandatory_regulations=[],
            framework_assessments=[],
            gap_risk_summary={
                "overall_risk_rating": "Low",
                "critical_gaps": ["Gap A"],
                "recommended_priority_actions": ["Action 1"],
                "estimated_remediation_effort": "Low",
                "executive_summary": "All good.",
            },
        )
        json_str = report.model_dump_json()
        restored = ComplianceReport.model_validate_json(json_str)
        self.assertEqual(report.report_id, restored.report_id)
        self.assertEqual(restored.gap_risk_summary.critical_gaps, ["Gap A"])


# ---------------------------------------------------------------------------
# Test 4 — Framework registry integrity
# ---------------------------------------------------------------------------

class TestFrameworkRegistry(unittest.TestCase):
    """Verify the registry data is well-formed and internally consistent."""

    REQUIRED_KEYS = {"full_name", "domains", "audit_topics", "industries", "listed_status"}

    def test_all_entries_have_required_keys(self):
        for fw_key, fw in FRAMEWORK_REGISTRY.items():
            with self.subTest(framework=fw_key):
                for k in self.REQUIRED_KEYS:
                    self.assertIn(k, fw, f"'{fw_key}' missing field '{k}'")

    def test_domains_are_non_empty_lists(self):
        for fw_key, fw in FRAMEWORK_REGISTRY.items():
            with self.subTest(framework=fw_key):
                self.assertIsInstance(fw["domains"], list)
                self.assertGreater(len(fw["domains"]), 0,
                                   f"'{fw_key}' has empty domains list")

    def test_full_names_are_non_empty_strings(self):
        for fw_key, fw in FRAMEWORK_REGISTRY.items():
            with self.subTest(framework=fw_key):
                self.assertIsInstance(fw["full_name"], str)
                self.assertTrue(fw["full_name"].strip(),
                                f"'{fw_key}' has blank full_name")

    def test_at_least_20_frameworks_registered(self):
        self.assertGreaterEqual(len(FRAMEWORK_REGISTRY), 20,
                                "Expected at least 20 frameworks in registry")

    def test_audit_topics_values_are_valid(self):
        from typing import get_args

        from saaf.core.models import AuditTopic
        valid_topics = set(get_args(AuditTopic)) | {"*"}
        for fw_key, fw in FRAMEWORK_REGISTRY.items():
            for topic in fw.get("audit_topics", []):
                with self.subTest(framework=fw_key, topic=topic):
                    self.assertIn(topic, valid_topics,
                                  f"'{fw_key}' has unknown audit_topic '{topic}'")


# ---------------------------------------------------------------------------
# Test 5 — System prompt builder
# ---------------------------------------------------------------------------

class TestSystemPromptBuilder(unittest.TestCase):
    """Verify the dynamic prompt builder produces a coherent, non-empty prompt."""

    def setUp(self):
        self.audit_input = _make_input(
            industry="Financial Services",
            country="US",
            listed_status="Public",
            audit_topic="Financial Reporting",
        )
        self.mapping = FrameworkMapper(self.audit_input).map()

    def test_system_prompt_is_non_empty(self):
        prompt = build_system_prompt(self.audit_input, self.mapping)
        self.assertTrue(prompt.strip())

    def test_system_prompt_contains_role_instruction(self):
        prompt = build_system_prompt(self.audit_input, self.mapping)
        self.assertIn("Senior Internal Audit", prompt)

    def test_system_prompt_injects_framework_names(self):
        prompt = build_system_prompt(self.audit_input, self.mapping)
        # At least one framework's full name should appear in the prompt
        found_any = any(
            m.full_name in prompt for m in self.mapping.framework_matches
        )
        self.assertTrue(found_any, "No framework full_names found in system prompt")

    def test_system_prompt_contains_json_schema(self):
        prompt = build_system_prompt(self.audit_input, self.mapping)
        self.assertIn("ComplianceReport", prompt)
        self.assertIn("gap_risk_summary", prompt)

    def test_user_message_contains_company_name(self):
        msg = build_user_message(self.audit_input, self.mapping)
        self.assertIn(self.audit_input.company_name, msg)

    def test_user_message_contains_audit_topic(self):
        msg = build_user_message(self.audit_input, self.mapping)
        self.assertIn(self.audit_input.audit_topic, msg)

    def test_user_message_lists_frameworks(self):
        msg = build_user_message(self.audit_input, self.mapping)
        self.assertIn("FRAMEWORKS IN SCOPE", msg)


# ---------------------------------------------------------------------------
# Grounding check — model output must stay within the mapped frameworks
# ---------------------------------------------------------------------------

class TestGroundingCheck(unittest.TestCase):
    def _report(self, fw_names, reg_names):
        return ComplianceReport(
            audit_input=_make_input(),
            mandatory_regulations=[
                {"regulation_name": n, "jurisdiction": "US", "mandatory": True,
                 "applicable_sections": [], "compliance_notes": "n"}
                for n in reg_names
            ],
            framework_assessments=[
                {"framework_name": n, "applicability_rationale": "r",
                 "control_objectives": [], "key_gaps": [], "risk_rating": "High"}
                for n in fw_names
            ],
            gap_risk_summary={
                "overall_risk_rating": "High", "critical_gaps": [],
                "recommended_priority_actions": [],
                "estimated_remediation_effort": "Medium", "executive_summary": "s",
            },
        )

    def setUp(self):
        self.mapping = FrameworkMapper(_make_input()).map()  # US / Healthcare / Private

    def test_mapped_names_accepted_in_variants(self):
        full = next(m.full_name for m in self.mapping.framework_matches if m.key == "HIPAA")
        report = self._report(
            [full, "hipaa"],
            ["HIPAA", "Health Insurance Portability and Accountability Act"],
        )
        ComplianceAgent._check_grounding(report, self.mapping)  # does not raise

    def test_out_of_scope_framework_rejected_with_raw_response(self):
        self.assertNotIn("SOX", self.mapping.applicable_framework_keys)
        report = self._report(["HIPAA", "Sarbanes-Oxley Act 2002 (SOX)"], [])
        with self.assertRaises(ComplianceReportError) as ctx:
            ComplianceAgent._check_grounding(report, self.mapping, raw_json="RAW")
        self.assertIn("Sarbanes-Oxley", str(ctx.exception))
        self.assertEqual(ctx.exception.raw_response, "RAW")

    def test_invented_regulation_rejected(self):
        report = self._report(["HIPAA"], ["Totally Invented Act 2031"])
        with self.assertRaises(ComplianceReportError):
            ComplianceAgent._check_grounding(report, self.mapping)

    def test_run_rejects_out_of_scope_framework_end_to_end(self):
        payload = self._report(["Totally Invented Act 2031"], []).model_dump_json()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}), \
                patch("saaf.core.agent.create_client"):
            agent = ComplianceAgent(Config())
        with patch.object(agent, "_call_llm", return_value=payload):
            with self.assertRaises(ComplianceReportError) as ctx:
                agent.run(_make_input())
        self.assertEqual(ctx.exception.raw_response, payload)


# ---------------------------------------------------------------------------
# Test 6 (new) — JSON extraction robustness (regression for invalid-JSON bug)
# ---------------------------------------------------------------------------

class TestJsonExtraction(unittest.TestCase):
    """
    Verify _extract_json_object handles all the ways Claude can wrap JSON.
    These tests cover the three bugs fixed:
      1. max_tokens too low (Config default raised to 16000)
      2. Preamble text before the JSON object
      3. Markdown fences around the JSON
    """

    def setUp(self):
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
        self.agent = ComplianceAgent.__new__(ComplianceAgent)  # skip __init__ (no real API)

    def test_clean_json_unchanged(self):
        raw = '{"key": "value"}'
        self.assertEqual(self.agent._extract_json_object(raw), raw)

    def test_strips_markdown_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = self.agent._extract_json_object(raw)
        self.assertEqual(json.loads(result), {"key": "value"})

    def test_strips_plain_code_fence(self):
        raw = '```\n{"key": "value"}\n```'
        result = self.agent._extract_json_object(raw)
        self.assertEqual(json.loads(result), {"key": "value"})

    def test_strips_preamble_text(self):
        """Claude sometimes writes 'Here is the JSON:' before the object."""
        raw = 'Here is the compliance report:\n\n{"report_id": "abc"}'
        result = self.agent._extract_json_object(raw)
        self.assertEqual(json.loads(result), {"report_id": "abc"})

    def test_strips_postamble_text(self):
        raw = '{"report_id": "abc"}\n\nLet me know if you need anything else.'
        result = self.agent._extract_json_object(raw)
        self.assertEqual(json.loads(result), {"report_id": "abc"})

    def test_strips_both_preamble_and_postamble(self):
        raw = 'Sure! Here you go:\n{"x": 1}\nHope that helps!'
        result = self.agent._extract_json_object(raw)
        self.assertEqual(json.loads(result), {"x": 1})

    def test_returns_text_as_is_when_no_braces(self):
        """If there's no JSON object at all, pass through so json.loads reports the error."""
        raw = "Sorry, I cannot generate this report."
        result = self.agent._extract_json_object(raw)
        self.assertEqual(result, raw)

    def test_max_tokens_is_at_least_16000(self):
        """Regression: max_tokens was 8192 causing truncated JSON."""
        import os
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        config = Config.__new__(Config)
        config.__dict__.update(Config.__dataclass_fields__)
        # Read default directly from the dataclass field
        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(Config)}
        self.assertGreaterEqual(
            defaults["max_tokens"], 32000,
            "max_tokens default must be >= 32000 to avoid JSON truncation"
        )


class TestClientTimeout(unittest.TestCase):
    """Config.timeout_seconds must be passed to the Anthropic client."""

    def test_timeout_passed_to_client(self) -> None:
        config = Config()
        config.timeout_seconds = 42
        with patch("anthropic.Anthropic") as mock_client:
            ComplianceAgent(config)
        mock_client.assert_called_once()
        self.assertEqual(mock_client.call_args.kwargs["timeout"], 42)


# ---------------------------------------------------------------------------
# Test 7 — CLI dry-run (end-to-end without API)
# ---------------------------------------------------------------------------

class TestCliDryRun(unittest.TestCase):  # was Test 6, now Test 7
    """
    Invoke the CLI as a subprocess in --dry-run mode.
    Verifies the CLI parses arguments correctly and the mapper pipeline
    runs end-to-end without touching the API.
    """

    PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    CLI = str(PROJECT_ROOT / "cli.py")

    def _run_cli(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        base_args = [
            self.PYTHON, self.CLI,
            "--company", "Test Corp",
            "--industry", "Healthcare",
            "--country", "US",
            "--listed-status", "Private",
            "--audit-topic", "Cybersecurity",
        ]
        return subprocess.run(
            base_args + extra_args,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

    def test_dry_run_exits_zero(self):
        result = self._run_cli(["--dry-run"])
        self.assertEqual(result.returncode, 0,
                         f"CLI exited non-zero.\nstdout: {result.stdout}\nstderr: {result.stderr}")

    def test_dry_run_shows_jurisdiction(self):
        result = self._run_cli(["--dry-run"])
        self.assertIn("Jurisdiction", result.stdout)
        self.assertIn("US", result.stdout)

    def test_dry_run_shows_frameworks(self):
        result = self._run_cli(["--dry-run"])
        self.assertIn("HIPAA", result.stdout,
                      "HIPAA should appear in dry-run output for US Healthcare Cybersecurity")

    def test_dry_run_no_api_key_needed(self):
        """Dry-run should work even with a dummy/missing API key."""
        env = {"ANTHROPIC_API_KEY": "dummy-key-for-dry-run"}
        result = subprocess.run(
            [
                self.PYTHON, self.CLI,
                "--company", "Test",
                "--industry", "Technology",
                "--country", "UK",
                "--listed-status", "Private",
                "--audit-topic", "IT General Controls",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_args_exits_nonzero(self):
        """CLI without required args and without --interactive should fail."""
        result = subprocess.run(
            [self.PYTHON, self.CLI, "--company", "Only Company"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_industry_rejected_by_cli(self):
        """argparse should reject an invalid --industry value."""
        result = subprocess.run(
            [
                self.PYTHON, self.CLI,
                "--company", "X", "--industry", "Astrology",
                "--country", "US", "--listed-status", "Private",
                "--audit-topic", "Cybersecurity",
            ],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr.lower(),
                      "argparse should report 'invalid choice'")


class TestKnowledgeBaseMetadata(unittest.TestCase):
    def test_kb_version_is_non_empty_string(self):
        self.assertIsInstance(KB_VERSION, str)
        self.assertTrue(KB_VERSION)

    def test_all_entries_have_metadata_keys(self):
        for key, fw in FRAMEWORK_REGISTRY.items():
            self.assertIn("last_reviewed", fw, key)
            self.assertIn("source", fw, key)

    def test_metadata_values_are_well_formed(self):
        from datetime import date
        for key, fw in FRAMEWORK_REGISTRY.items():
            if fw["last_reviewed"] is not None:
                date.fromisoformat(fw["last_reviewed"])  # raises if malformed
            if fw["source"] is not None:
                self.assertTrue(fw["source"].strip(), key)

    def test_report_entries_missing_review_date(self):
        # Informational: lists entries a maintainer still needs to review.
        # Deliberately does not fail, so dates are only ever set honestly.
        missing = sorted(k for k, fw in FRAMEWORK_REGISTRY.items()
                         if fw["last_reviewed"] is None)
        print("\nFrameworks missing last_reviewed: %d/%d: %s"
              % (len(missing), len(FRAMEWORK_REGISTRY), ", ".join(missing)))


class TestDisclaimerNotOverridable(unittest.TestCase):
    """The standard disclaimer must survive any model-supplied value (CO-3)."""

    def setUp(self):
        self.agent = ComplianceAgent.__new__(ComplianceAgent)  # skip __init__ (no real API)
        self.ai = _make_input()

    def _response(self, **extra) -> str:
        data = {
            "mandatory_regulations": [],
            "framework_assessments": [],
            "gap_risk_summary": {
                "overall_risk_rating": "High",
                "critical_gaps": [],
                "recommended_priority_actions": [],
                "estimated_remediation_effort": "Medium",
                "executive_summary": "Test summary.",
            },
        }
        data.update(extra)
        return json.dumps(data)

    def test_schema_hides_disclaimer_from_model(self):
        prompt = build_system_prompt(self.ai, FrameworkMapper(self.ai).map())
        self.assertNotIn('"disclaimer"', prompt)

    def test_omitted_disclaimer_gets_standard_text(self):
        report = self.agent._parse_and_validate(self._response(), self.ai)
        self.assertEqual(report.disclaimer, DISCLAIMER)

    def test_rewritten_disclaimer_is_replaced(self):
        raw = self._response(disclaimer="This report is audit-ready and legally binding.")
        report = self.agent._parse_and_validate(raw, self.ai)
        self.assertEqual(report.disclaimer, DISCLAIMER)

    def test_disclaimer_in_json_output(self):
        raw = self._response(disclaimer="ignore me")
        report = self.agent._parse_and_validate(raw, self.ai)
        self.assertEqual(json.loads(report.model_dump_json())["disclaimer"], DISCLAIMER)

    def test_disclaimer_in_rendered_report(self):
        report = self.agent._parse_and_validate(self._response(disclaimer="x"), self.ai)
        with formatter.console.capture() as cap:
            formatter.render_report(report)
        rendered = " ".join(cap.get().replace("│", " ").split())
        self.assertIn(DISCLAIMER, rendered)


# ---------------------------------------------------------------------------
# Test 8 — Entity-name data flow (warning and alias; no API calls)
# ---------------------------------------------------------------------------

class TestEntityNameDataFlow(unittest.TestCase):
    """Drives cli.main() in-process with a mocked ComplianceAgent."""

    REAL = "Real Bank NV"

    def _main(self, extra: list[str]):
        import io

        import cli
        sent: list[AuditInput] = []

        def fake_run(audit_input):
            sent.append(audit_input)
            report = ComplianceReport.model_construct(
                report_id="r1", audit_input=audit_input, mandatory_regulations=[],
                framework_assessments=[], gap_risk_summary=None, disclaimer="d",
            )
            return report, MagicMock()

        argv = ["saaf", "--company", self.REAL, "--industry", "Healthcare",
                "--country", "US", "--listed-status", "Private",
                "--audit-topic", "Cybersecurity", "--output", "json"] + extra
        err = io.StringIO()
        with patch.object(sys, "argv", argv), \
             patch.object(cli, "Config", return_value=MagicMock()), \
             patch.object(cli, "ComplianceAgent") as agent_cls, \
             patch.object(cli, "err_console", cli.Console(file=err, width=200)), \
             patch.object(cli, "console", cli.Console(file=io.StringIO())), \
             patch.object(ComplianceReport, "model_dump_json",
                          lambda self, **kw: self.audit_input.model_dump_json()), \
             patch("builtins.print") as printed:
            agent_cls.return_value.run.side_effect = fake_run
            rc = cli.main()
        out = "".join(str(c.args[0]) for c in printed.call_args_list)
        return rc, sent, err.getvalue(), out

    def test_default_warns_and_sends_real_name(self):
        rc, sent, err, _ = self._main([])
        self.assertEqual(rc, 0)
        self.assertIn("sent verbatim", err)
        self.assertEqual(sent[0].company_name, self.REAL)

    def test_yes_suppresses_warning(self):
        for flag in ("--yes", "--no-warn"):
            rc, sent, err, _ = self._main([flag])
            self.assertEqual(rc, 0)
            self.assertNotIn("sent verbatim", err)

    def test_dry_run_does_not_warn(self):
        import io

        import cli
        err = io.StringIO()
        argv = ["saaf", "--company", self.REAL, "--industry", "Healthcare", "--country", "US",
                "--listed-status", "Private", "--audit-topic", "Cybersecurity", "--dry-run"]
        with patch.object(sys, "argv", argv), \
             patch.object(cli, "err_console", cli.Console(file=err)), \
             patch.object(cli, "console", cli.Console(file=io.StringIO())):
            self.assertEqual(cli.main(), 0)
        self.assertNotIn("sent verbatim", err.getvalue())

    def test_anonymise_sends_alias_not_real_name(self):
        rc, sent, err, _ = self._main(["--anonymise"])
        self.assertEqual(sent[0].company_name, "Entity A")
        self.assertNotIn(self.REAL, sent[0].model_dump_json())
        self.assertNotIn("sent verbatim", err)

    def test_alias_implies_anonymise(self):
        _, sent, _, _ = self._main(["--alias", "Client X"])
        self.assertEqual(sent[0].company_name, "Client X")

    def test_anonymised_output_restores_real_name_locally(self):
        _, _, _, out = self._main(["--anonymise"])
        self.assertIn(self.REAL, out)

    def test_real_name_not_logged_when_anonymised(self):
        """The agent logs the input it receives; with an alias that is never the real name."""
        import cli
        with patch("saaf.core.agent.create_client"):
            agent = ComplianceAgent(MagicMock())
        sent = cli.apply_alias(_make_input(company_name=self.REAL), "Entity A")
        with patch.object(agent, "_call_llm", side_effect=RuntimeError("stop")), \
             self.assertLogs("saaf.agent", level="DEBUG") as cm:
            with self.assertRaises(RuntimeError):
                agent.run(sent)
        logged = "\n".join(cm.output)
        self.assertNotIn(self.REAL, logged)
        self.assertIn("Entity A", logged)


# ---------------------------------------------------------------------------
# Test 9 — Unrecognised jurisdiction warning (issue #10)
# ---------------------------------------------------------------------------

_MINIMAL_REPORT = {
    "mandatory_regulations": [],
    "framework_assessments": [],
    "gap_risk_summary": {
        "overall_risk_rating": "Low",
        "critical_gaps": [],
        "recommended_priority_actions": [],
        "estimated_remediation_effort": "Low",
        "executive_summary": "Summary.",
    },
    "warnings": ["model supplied warning"],
}


class TestJurisdictionWarning(unittest.TestCase):
    PYTHON = TestCliDryRun.PYTHON
    CLI = TestCliDryRun.CLI

    def _agent(self):
        agent = ComplianceAgent.__new__(ComplianceAgent)
        agent._call_llm = lambda *a, **k: json.dumps(_MINIMAL_REPORT)
        return agent

    def test_warning_none_for_supported(self):
        for country in ["US", "Germany", "UK", "Australia", "Singapore"]:
            with self.subTest(country=country):
                self.assertIsNone(jurisdiction_warning(country))

    def test_warning_for_unknown(self):
        self.assertIn("Brazil", jurisdiction_warning("Brazil"))

    def test_agent_logs_and_sets_report_warning(self):
        with self.assertLogs("saaf.agent", level="WARNING") as cm:
            report, _ = self._agent().run(_make_input(country="Brazil"))
        self.assertTrue(any("Brazil" in m for m in cm.output))
        self.assertEqual(report.warnings, [jurisdiction_warning("Brazil")])

    def test_agent_overrides_model_supplied_warnings(self):
        report, _ = self._agent().run(_make_input(country="US"))
        self.assertEqual(report.warnings, [])

    def test_warnings_not_in_model_schema(self):
        self.assertNotIn('"warnings"', build_system_prompt(
            _make_input(), FrameworkMapper(_make_input()).map()))

    def test_formatter_renders_warning(self):
        from rich.console import Console

        from saaf.output import formatter
        report, _ = self._agent().run(_make_input(country="Brazil"))
        console = Console(record=True, width=120)
        with patch.object(formatter, "console", console):
            formatter.render_report(report)
        self.assertIn("not recognised", console.export_text())

    def test_cli_dry_run_warns_on_stderr(self):
        result = subprocess.run(
            [self.PYTHON, self.CLI, "--company", "X", "--industry", "Healthcare",
             "--country", "Brazil", "--listed-status", "Private",
             "--audit-topic", "Cybersecurity", "--dry-run"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("not recognised", result.stderr)

    def test_cli_no_warning_for_supported(self):
        result = subprocess.run(
            [self.PYTHON, self.CLI, "--company", "X", "--industry", "Healthcare",
             "--country", "US", "--listed-status", "Private",
             "--audit-topic", "Cybersecurity", "--dry-run"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        self.assertNotIn("not recognised", result.stderr)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
