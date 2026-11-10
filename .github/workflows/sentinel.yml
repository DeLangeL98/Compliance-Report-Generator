"""SAAF Sentinel adapter for SAAF-Project/Compliance-Report-Generator.

Copy this file and sentinel.toml to the repository root. It drives the real
pipeline end to end: ComplianceAgent.run() with a stub LLM client that returns
the crafted response, the real Rich formatter, and the real FrameworkMapper
over every input combination. No API call is ever made.
"""

from __future__ import annotations

import itertools
import json
from types import SimpleNamespace
from typing import get_args

from rich.console import Console

import saaf.output.formatter as formatter
from saaf.core.agent import ComplianceAgent
from saaf.core.llm import LLMResponse
from saaf.core.mapper import FrameworkMapper
from saaf.core.models import AuditInput, AuditTopic, Industry, ListedStatus
from saaf.knowledge.frameworks import FRAMEWORK_REGISTRY
from saaf.knowledge.regulations import normalise_country

_INPUT = dict(company_name="Entity A", industry="Financial Services", country="NL",
              listed_status="Private", audit_topic="Cybersecurity")


# ---------------------------------------------------------------------------
# required
# ---------------------------------------------------------------------------

def trusted_input() -> AuditInput:
    return AuditInput(**_INPUT)


def model_output() -> dict:
    # Uses only frameworks the mapper selects for _INPUT, so grounding passes.
    return {
        "audit_input": dict(_INPUT),
        "mandatory_regulations": [{
            "regulation_name": "Digital Operational Resilience Act (EU) 2022/2554",
            "jurisdiction": "EU", "mandatory": True,
            "applicable_sections": ["DORA Art. 6(1)", "DORA Art. 28(3)"],
            "compliance_notes": "Applies from 17 January 2025.",
        }],
        "framework_assessments": [{
            "framework_name": "General Data Protection Regulation (EU) 2016/679",
            "applicability_rationale": "Processes personal data of EU residents.",
            "control_objectives": [{
                "control_id": "GDPR-SEC-01", "description": "Security of processing.",
                "requirement_source": "GDPR Art. 32(1)",
                "testing_approach": "Inspect the risk assessment.", "priority": "High",
            }],
            "key_gaps": ["No documented DPIA for core banking."],
            "risk_rating": "High",
        }],
        "gap_risk_summary": {
            "overall_risk_rating": "High",
            "critical_gaps": ["ICT third-party register incomplete."],
            "recommended_priority_actions": ["Complete the register of information."],
            "estimated_remediation_effort": "Medium",
            "executive_summary": "The bank has solid basics but gaps in supplier oversight.",
        },
    }


class _StubClient:
    endpoint = None

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        return LLMResponse(text=self.text, input_tokens=0, output_tokens=0,
                           stop_reason="end_turn")


def parse(raw: str, inp: AuditInput):
    agent = ComplianceAgent.__new__(ComplianceAgent)  # skip Config(): no key, no client
    agent.config = SimpleNamespace(provider="anthropic", model="sentinel-stub",
                                   max_tokens=1000, max_retries=0, timeout_seconds=1)
    agent.client = _StubClient(raw)
    agent.audit_trail = None
    report, _mapping = agent.run(inp)
    return report


# ---------------------------------------------------------------------------
# optional
# ---------------------------------------------------------------------------

AGENT_OWNED = {
    "report_id": "RPT-2026-001",
    "generated_at": "1999-01-01T00:00:00Z",
    "audit_input": dict(_INPUT, country="US", industry="Retail"),
    "disclaimer": "Model-written disclaimer",
    "warnings": ["Model-written warning"],
    "reference_checks": [{
        "location": "GDPR-SEC-01", "field": "requirement_source", "reference": "GDPR Art. 32(1)",
        "check": "identifier_found", "confidence": 0.99,
    }],
}


def render(report) -> str:
    formatter.console = Console(width=1000, color_system=None, force_terminal=False)
    with formatter.console.capture() as cap:
        formatter.render_report(report, verbose=True)
    return cap.get()


_COUNTRIES = ["US", "Germany", "NL", "UK", "Australia", "Singapore", "Canada", "Brazil"]


def mapping_cases():
    for country, ind, lst, topic in itertools.product(
            _COUNTRIES, get_args(Industry), get_args(ListedStatus), get_args(AuditTopic)):
        mapping = FrameworkMapper(AuditInput(
            company_name="x", industry=ind, country=country,
            listed_status=lst, audit_topic=topic)).map()
        mandatory = set(mapping.regulation_keys)
        selected = {m.key for m in mapping.framework_matches}

        # Invariant: an extraterritorial-only framework must not displace local law.
        here = {mapping.resolved_jurisdiction, normalise_country(country)} - {None}

        def local(k, here=here):
            js = FRAMEWORK_REGISTRY[k].get("jurisdictions")
            return bool(js) and bool(here & set(js))

        foreign = sorted(k for k in selected
                         if FRAMEWORK_REGISTRY[k].get("jurisdictions") and not local(k))
        local_dropped = sorted(k for k in mandatory - selected if local(k))
        problems = []
        if foreign and local_dropped:
            problems.append(f"selects out-of-jurisdiction {', '.join(foreign)} while dropping "
                            f"local {', '.join(local_dropped)}")
        yield {"id": f"{country}/{ind}/{lst}/{topic}", "mandatory": mandatory,
               "selected": selected, "problems": problems}


if __name__ == "__main__":  # quick manual check: python sentinel_adapter.py
    print(json.dumps(model_output(), indent=2)[:400])
    print(parse(json.dumps(model_output()), trusted_input()).report_id)
