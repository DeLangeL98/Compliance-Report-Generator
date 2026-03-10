"""
Dynamic system prompt builder.

Assembles three sections:
  A. Static role and reasoning instructions
  B. Dynamic framework knowledge (only relevant frameworks)
  C. Output schema instructions
"""

from __future__ import annotations

import json

from saaf.core.models import AuditInput, ComplianceReport
from saaf.core.mapper import MappingResult


# ---------------------------------------------------------------------------
# Section A — Role (static)
# ---------------------------------------------------------------------------

_ROLE_SECTION = """\
You are a Senior Internal Audit and Compliance Specialist with 20+ years of experience
across regulatory compliance, risk management, and internal audit engagements spanning
Financial Services, Healthcare, Technology, Energy, and Government sectors.

Your expertise covers:
- Internal audit methodology (IIA Standards, risk-based auditing)
- Regulatory compliance across major jurisdictions (US, EU, UK, Australia, Singapore)
- IT General Controls (ITGCs), cybersecurity frameworks, and data privacy law
- ESG reporting standards and sustainability assurance
- Anti-money laundering and financial crime prevention

TASK:
Produce a structured compliance report in valid JSON for the engagement described in the
user message. The report must cover:
1. The mandatory regulations and their specific applicable sections
2. A framework-by-framework assessment with concrete control objectives, testing approaches,
   and key gaps typical for this type of organisation
3. An overall risk and gap summary with executive-level commentary

REASONING RULES:
- Only reference regulations and frameworks listed in the PROVIDED FRAMEWORKS section below.
  Do not invent or hallucinate additional frameworks.
- Apply professional scepticism. Where a control objective requires entity-specific information
  to assess properly, note this in the testing approach or gaps.
- Control IDs should be short and unique (e.g. "ISO-AC-01", "SOX-ITGC-03", "GDPR-PP-02").
- Be specific — generic boilerplate ("implement appropriate controls") is unacceptable.
  Reference actual clause numbers, rule names, or technical requirements.
- Risk ratings should reflect the combined effect of likelihood and impact for a typical
  organisation matching the described profile.
- The executive_summary must be jargon-free and understandable by a non-technical board member.

OUTPUT RULES:
- Return ONLY valid JSON — no markdown, no code fences, no prose before or after.
- The JSON must be directly parseable by json.loads().
- Follow the schema exactly. Do not add or remove fields.
"""


# ---------------------------------------------------------------------------
# Section B — Dynamic framework knowledge
# ---------------------------------------------------------------------------

def _build_framework_section(mapping: MappingResult) -> str:
    lines = ["=" * 60, "PROVIDED FRAMEWORKS (use ONLY these)", "=" * 60, ""]

    for match in mapping.framework_matches:
        lines.append(f"FRAMEWORK: {match.full_name}")
        lines.append(f"Key: {match.key}")
        lines.append(f"Why applicable: {match.rationale}")
        lines.append(f"Description: {match.description}")
        if match.relevant_domains:
            lines.append("Relevant control domains for this engagement:")
            for d in match.relevant_domains:
                lines.append(f"  - {d}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section C — Output schema (static but derived from Pydantic model)
# ---------------------------------------------------------------------------

def _build_schema_section() -> str:
    schema = ComplianceReport.model_json_schema()
    schema_str = json.dumps(schema, indent=2)
    return (
        "=" * 60 + "\n"
        "OUTPUT JSON SCHEMA\n"
        "=" * 60 + "\n"
        "Your response must conform exactly to this schema:\n\n"
        + schema_str
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_system_prompt(audit_input: AuditInput, mapping: MappingResult) -> str:
    return "\n\n".join([
        _ROLE_SECTION,
        _build_framework_section(mapping),
        _build_schema_section(),
    ])


def build_user_message(audit_input: AuditInput, mapping: MappingResult) -> str:
    fw_names = [m.full_name for m in mapping.framework_matches]
    reg_names = []
    for key in mapping.regulation_keys:
        # Get the full name from framework matches or registry
        for m in mapping.framework_matches:
            if m.key == key:
                reg_names.append(m.full_name)
                break

    return f"""\
Generate a comprehensive compliance report for the following engagement:

ENGAGEMENT DETAILS:
  Company:        {audit_input.company_name}
  Industry:       {audit_input.industry}
  Country:        {audit_input.country} (resolved jurisdiction: {mapping.resolved_jurisdiction})
  Listed Status:  {audit_input.listed_status}
  Audit Topic:    {audit_input.audit_topic}

FRAMEWORKS IN SCOPE ({len(fw_names)} identified):
{chr(10).join(f"  - {name}" for name in fw_names)}

INSTRUCTIONS:
For each framework, provide:
  - applicability_rationale: why this specific framework applies to THIS organisation profile
  - 3–5 control objectives specific to {audit_input.audit_topic} in {audit_input.industry}
  - Each control objective needs: control_id, description, requirement_source (exact clause),
    testing_approach (specific audit procedure), and priority
  - key_gaps: 3–5 gaps a typical {audit_input.industry} {audit_input.listed_status} company
    faces with this framework for {audit_input.audit_topic}
  - risk_rating: based on typical compliance maturity for this profile

For mandatory_regulations, list each applicable regulation separately with:
  - applicable_sections: the specific articles/sections/rules that apply
  - compliance_notes: key deadlines, penalties, or obligations

Ensure the gap_risk_summary provides a prioritised action plan and an executive_summary
that a board member with no technical background could understand.

Return the complete ComplianceReport JSON now.
"""
