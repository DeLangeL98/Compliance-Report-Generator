"""Convert a ComplianceReport into SAAF finding-schema records.

Target schema: ``outputs/schemas/finding-schema.json`` in SAAF-Project/SAAF-Project.

Mapping decisions (all values are derived from fields of the report only):

* Risk rating: the schema allows High / Medium / Low / Informational, while this
  agent also uses ``Critical``. ``Critical`` is mapped to ``High`` (the schema's
  highest level); High, Medium and Low map to themselves. ``Informational`` is
  never produced because the report carries no such rating.
* ``gap_risk_summary.critical_gaps`` -> one finding each, rated High. The
  original text is the observation and the whole
  ``recommended_priority_actions`` list is the recommendation (the report does
  not link individual actions to individual gaps).
* ``framework_assessments[].key_gaps`` -> one finding each, rated with the
  framework's ``risk_rating`` (mapped as above). The recommendation points at
  the framework's own control objectives; if it has none, the summary's
  priority actions are used. A key gap whose text equals a critical gap
  (case-insensitive) is skipped as a duplicate.
* ``id`` is sequential (F-01, F-02, ...); ``title`` is the gap text truncated to
  the schema's 100 characters; ``control_objective`` is the framework name for
  framework gaps; ``ai_assisted`` is True and ``status`` is "Open".
* Fields the report cannot support (root_cause, impact, owner, target_date,
  management_response, evidence_references) are omitted rather than invented.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

TITLE_MAX_LENGTH = 100
_MAX_FINDINGS = 9999
_NO_ACTION = "No priority action was specified in the report; to be determined by the auditor."

# Agent rating -> finding-schema enum value.
RISK_RATING_MAP: Dict[str, str] = {
    "Critical": "High",
    "High": "High",
    "Medium": "Medium",
    "Low": "Low",
}


def _title(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TITLE_MAX_LENGTH:
        return text
    return text[: TITLE_MAX_LENGTH - 3].rstrip() + "..."


def _actions_text(actions: List[str]) -> str:
    if not actions:
        return _NO_ACTION
    return "Priority actions from the report: " + "; ".join(actions)


def report_to_findings(report: Any) -> List[Dict[str, Any]]:
    """Return schema-conformant finding dicts derived from ``report``.

    ``report`` is a ``saaf.core.models.ComplianceReport`` (any object exposing
    the same attributes works). The function is pure: no I/O, no mutation.
    """
    summary = report.gap_risk_summary
    actions = list(summary.recommended_priority_actions)
    findings: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add(gap: str, rating: str, observation: str, recommendation: str,
            control_objective: str = "") -> None:
        if len(findings) >= _MAX_FINDINGS:
            raise ValueError("Too many findings for the F-NN[NN] id pattern")
        finding: Dict[str, Any] = {
            "id": "F-{:02d}".format(len(findings) + 1),
            "title": _title(gap),
            "risk_rating": RISK_RATING_MAP[rating],
            "observation": observation,
            "recommendation": recommendation,
            "status": "Open",
            "ai_assisted": True,
        }
        if control_objective:
            finding["control_objective"] = control_objective
        findings.append(finding)

    for gap in summary.critical_gaps:
        key = " ".join(gap.split()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        add(gap, "Critical", gap, _actions_text(actions))

    for fw in report.framework_assessments:
        controls = [
            "{} ({})".format(c.control_id, c.requirement_source)
            for c in fw.control_objectives
        ]
        if controls:
            recommendation = "Remediate against the {} control objectives: {}.".format(
                fw.framework_name, "; ".join(controls))
        else:
            recommendation = _actions_text(actions)
        for gap in fw.key_gaps:
            key = " ".join(gap.split()).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            add(gap, fw.risk_rating,
                "{} (framework: {})".format(gap, fw.framework_name),
                recommendation, fw.framework_name)

    return findings
