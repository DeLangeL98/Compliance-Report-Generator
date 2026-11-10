"""Finding type and output formats (text, GitHub annotations, SARIF, Markdown summary)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional

SEVERITIES = ("info", "warning", "error")
_SARIF_LEVEL = {"info": "note", "warning": "warning", "error": "error"}
_GH_LEVEL = {"info": "notice", "warning": "warning", "error": "error"}


@dataclass
class Finding:
    rule: str                 # e.g. "SEN001" or "CT003"
    severity: str             # info | warning | error
    message: str
    path: Optional[str] = None
    line: Optional[int] = None
    hint: str = ""
    details: List[str] = field(default_factory=list)

    def where(self) -> str:
        if not self.path:
            return "-"
        return f"{self.path}:{self.line}" if self.line else self.path


RULES = {
    # static
    "SEN001": ("markup-injection", "Untrusted text interpolated into a Rich markup string"),
    "SEN002": ("retry-without-backoff", "Retry loop retries immediately (no sleep/backoff)"),
    "SEN003": ("silent-truncation", "Result list is cut to a fixed length without a warning"),
    "SEN004": ("unchecked-stop-reason", "Stop/finish reason is read but never checked"),
    "SEN005": ("model-output-splat", "Parsed model JSON is splatted into a model class"),
    "SEN006": ("unpinned-action", "GitHub Action pinned to a tag or branch, not a commit SHA"),
    # contract
    "CT001": ("agent-owned-field", "Model output can set a field the agent must own"),
    "CT002": ("render-injection", "Renderer crashes on or mangles model-supplied markup"),
    "CT003": ("mapping-completeness", "Mapping drops mandatory items or breaks an invariant"),
    "CT004": ("empty-report-accepted", "An empty or content-free model response is accepted"),
}


def at_least(findings: Iterable[Finding], level: str) -> List[Finding]:
    floor = SEVERITIES.index(level)
    return [f for f in findings if SEVERITIES.index(f.severity) >= floor]


def to_text(findings: List[Finding]) -> str:
    if not findings:
        return "SAAF Sentinel: no findings."
    lines = []
    for f in sorted(findings, key=lambda x: (-SEVERITIES.index(x.severity), x.rule, x.where())):
        name = RULES.get(f.rule, ("", ""))[0]
        lines.append(f"{f.severity.upper():7} {f.rule} {name:24} {f.where()}")
        lines.append(f"        {f.message}")
        lines.extend(f"          - {d}" for d in f.details[:20])
        if len(f.details) > 20:
            lines.append(f"          ... {len(f.details) - 20} more")
        if f.hint:
            lines.append(f"        fix: {f.hint}")
    counts = {s: sum(f.severity == s for f in findings) for s in SEVERITIES}
    lines.append(f"\n{len(findings)} finding(s): "
                 + ", ".join(f"{counts[s]} {s}" for s in reversed(SEVERITIES)))
    return "\n".join(lines)


def to_github_annotations(findings: List[Finding]) -> str:
    out = []
    for f in findings:
        loc = ""
        if f.path:
            loc = f" file={f.path}" + (f",line={f.line}" if f.line else "")
        msg = f"{f.message}" + (f" Fix: {f.hint}" if f.hint else "")
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        out.append(f"::{_GH_LEVEL[f.severity]}{loc},title=Sentinel {f.rule}::{msg}")
    return "\n".join(out)


def to_markdown(findings: List[Finding]) -> str:
    if not findings:
        return "### SAAF Sentinel\n\nNo findings. :white_check_mark:\n"
    rows = ["### SAAF Sentinel", "", "| Severity | Rule | Where | Finding |", "|---|---|---|---|"]
    for f in sorted(findings, key=lambda x: (-SEVERITIES.index(x.severity), x.rule)):
        msg = f.message.replace("|", "\\|")
        rows.append(f"| {f.severity} | `{f.rule}` | `{f.where()}` | {msg} |")
    return "\n".join(rows) + "\n"


def to_sarif(findings: List[Finding], version: str) -> str:
    rules = [
        {"id": rid, "name": name, "shortDescription": {"text": desc}}
        for rid, (name, desc) in RULES.items()
    ]
    results = []
    for f in findings:
        r = {
            "ruleId": f.rule,
            "level": _SARIF_LEVEL[f.severity],
            "message": {"text": f.message + (f" Fix: {f.hint}" if f.hint else "")},
        }
        if f.path:
            region = {"startLine": f.line} if f.line else {}
            r["locations"] = [{"physicalLocation": {
                "artifactLocation": {"uri": f.path}, **({"region": region} if region else {})}}]
        results.append(r)
    return json.dumps({
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {"name": "SAAF Sentinel", "version": version, "rules": rules}},
            "results": results,
        }],
    }, indent=2)


def to_json(findings: List[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], indent=2)
