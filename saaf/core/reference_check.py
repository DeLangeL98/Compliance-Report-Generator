"""
Heuristic sanity check for model-generated clause references.

IMPORTANT: this module does NOT verify that a clause, article or section
exists or says what the model claims. The repository holds no source text for
the frameworks. The only check performed is that a reference *names* a
framework or regulation that is in the mapped set for this audit. Every
reference, including those that pass this check, remains unverified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Set

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from saaf.core.mapper import MappingResult
    from saaf.core.models import ComplianceReport

UNVERIFIED_NOTE = (
    "Clause and section references are model-generated and have NOT been "
    "verified against source text. Confirm each reference against the "
    "official standard or regulation before relying on it."
)

_MIN_ALIAS_LEN = 3


@dataclass(frozen=True)
class SuspectReference:
    """A reference that does not name any framework in the mapped set."""

    location: str  # e.g. "ISO-AC-01" or "GDPR (regulation)"
    field: str  # "requirement_source" or "applicable_sections"
    reference: str
    reason: str


def _compact(text: str) -> str:
    """Lowercase and strip everything except letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _aliases_for(key: str, full_name: str) -> Set[str]:
    """Build compact alias strings that identify one framework."""
    aliases: Set[str] = {_compact(key)}
    head = re.split(r"\s+[—–-]\s+", full_name, maxsplit=1)[0]
    for part in re.split(r"\s*/\s*|\s+&\s+", head):
        aliases.add(_compact(part))
    # "ISO/IEC 27001:2022" -> also accept "ISO 27001"
    aliases.add(_compact(re.sub(r"(?i)\bIEC\b", "", head.replace("/", " "))))
    # Parenthetical acronyms such as "(SOX)" or "(CCPA/CPRA)"
    for group in re.findall(r"\(([^)]*)\)", full_name):
        for part in re.split(r"\s*/\s*", group):
            aliases.add(_compact(part))
    return {a for a in aliases if len(a) >= _MIN_ALIAS_LEN}


def mapped_aliases(mapping: "MappingResult") -> Set[str]:
    """Collect compact aliases for every framework in the mapped set."""
    aliases: Set[str] = set()
    for match in mapping.framework_matches:
        aliases |= _aliases_for(match.key, match.full_name)
    return aliases


def _names_mapped_framework(reference: str, aliases: Set[str]) -> bool:
    compact = _compact(reference)
    return any(alias in compact for alias in aliases)


def find_suspect_references(
    report: "ComplianceReport", mapping: "MappingResult"
) -> List[SuspectReference]:
    """
    Return references that do not name any framework in the mapped set.

    Checks ControlObjective.requirement_source and
    RegulatoryRequirement.applicable_sections. A reference that names no
    mapped framework (for example a regulation outside the mapped set) is
    reported. An empty result does NOT mean references are
    correct, only that each names a mapped framework.

    Context rule: a bare clause (e.g. "A.8.3") is accepted when its parent
    framework assessment or regulation itself names a mapped framework. This
    is lenient by design and still not a verification of the clause.
    """
    aliases = mapped_aliases(mapping)
    suspects: List[SuspectReference] = []

    for fw in report.framework_assessments:
        parent_ok = _names_mapped_framework(fw.framework_name, aliases)
        for ctrl in fw.control_objectives:
            ref = ctrl.requirement_source
            if _names_mapped_framework(ref, aliases):
                continue
            if parent_ok:
                continue
            suspects.append(SuspectReference(
                location=ctrl.control_id,
                field="requirement_source",
                reference=ref,
                reason="names no framework in the mapped set",
            ))

    for reg in report.mandatory_regulations:
        reg_ok = _names_mapped_framework(reg.regulation_name, aliases)
        for section in reg.applicable_sections:
            if _names_mapped_framework(section, aliases) or reg_ok:
                continue
            suspects.append(SuspectReference(
                location=f"{reg.regulation_name} (regulation)",
                field="applicable_sections",
                reference=section,
                reason="names no framework in the mapped set",
            ))

    return suspects
