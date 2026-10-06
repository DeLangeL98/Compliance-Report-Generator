"""
Checks on model-generated clause references.

Two layers, neither of which verifies what a clause SAYS:

1. ``find_suspect_references`` - a reference must *name* a framework or
   regulation in the mapped set for this audit.
2. ``check_references`` - where the framework has an official clause list
   (``saaf/knowledge/clause_data``), the clause locator (article, paragraph,
   section, control ...) is compared with it. A match proves the clause EXISTS
   in the official text, nothing more.

Every reference, including those that pass both checks, stays "unverified".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from saaf.core.clause_check import (
    FOUND_EXACT,
    FOUND_PARENT,
    match_locators,
    parse_locators,
)
from saaf.knowledge.clauses import CLAUSE_LISTS, ClauseList, frameworks_named

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from saaf.core.mapper import MappingResult
    from saaf.core.models import ComplianceReport

UNVERIFIED_NOTE = (
    "Clause and section references are model-generated and have NOT been "
    "verified against source text. Where a framework has an official clause "
    "list, each reference was only checked for whether the cited clause exists; "
    "that does not confirm the clause says what the report claims. Confirm each "
    "reference against the official standard or regulation before relying on it."
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


# ---------------------------------------------------------------------------
# Clause-list check (issue #7)
# ---------------------------------------------------------------------------

# Check outcome -> confidence score. A heuristic ranking of how far a reference
# has been corroborated, NOT a probability. Never 1.0: clause content is not
# verified, so even an identifier that exists can be cited for the wrong reason.
CONFIDENCE: Dict[str, float] = {
    "identifier_found": 0.70,         # clause exists at the cited depth
    "parent_identifier_found": 0.60,  # cited deeper than the list; parent exists
    "no_locator": 0.25,               # framework named, nothing checkable cited
    "framework_not_covered": 0.30,    # mapped framework has no clause list yet
    "identifier_not_found": 0.10,     # not in the official list: likely invented
    "unmapped_framework": 0.05,       # names no framework in the mapped set
}


@dataclass(frozen=True)
class ReferenceCheckResult:
    """Outcome for one reference (mirrored by ``models.ReferenceCheck``)."""

    location: str
    field: str  # "requirement_source" or "applicable_sections"
    reference: str
    check: str
    confidence: float
    framework_key: Optional[str] = None
    status: str = "unverified"
    matched_identifiers: List[str] = field(default_factory=list)
    note: str = ""


def _result(location: str, fld: str, ref: str, check: str, *, key: Optional[str] = None,
            matched: Optional[List[str]] = None, note: str = "") -> ReferenceCheckResult:
    return ReferenceCheckResult(
        location=location, field=fld, reference=ref, check=check,
        confidence=CONFIDENCE[check], framework_key=key,
        matched_identifiers=matched or [], note=note,
    )


def check_reference(
    location: str,
    fld: str,
    reference: str,
    parent_name: str,
    mapped_keys: Set[str],
    aliases: Set[str],
    clause_lists: Dict[str, ClauseList],
) -> ReferenceCheckResult:
    """Check one reference. A bare clause takes its framework from ``parent_name``."""
    # The reference's own framework wins; the parent's is only used for a bare
    # clause that names no framework at all (so "SOX Section 404" inside a GLBA
    # assessment is never checked against GLBA).
    named = frameworks_named(reference) or frameworks_named(parent_name)
    covered = [k for k in named if k in clause_lists]

    if covered:
        in_scope = [k for k in covered if k in mapped_keys]
        if not in_scope:
            return _result(location, fld, reference, "unmapped_framework", key=covered[0],
                           note=f"{covered[0]} is not in the mapped set for this audit")
        key = in_scope[0]
        locators = parse_locators(reference)
        matches = match_locators(locators, [clause_lists[k] for k in in_scope], reference)
        if not matches:
            return _result(location, fld, reference, "no_locator", key=key,
                           note="no clause locator (article, section, control ...) found to check")
        matched = list(dict.fromkeys(m.identifier for m in matches if m.identifier))
        missing = [m for m in matches if m.outcome not in (FOUND_EXACT, FOUND_PARENT)]
        if missing:
            return _result(location, fld, reference, "identifier_not_found", key=key,
                           matched=matched,
                           note="; ".join(f"{m.locator.display()}: {m.detail}" for m in missing))
        if all(m.outcome == FOUND_EXACT for m in matches):
            return _result(location, fld, reference, "identifier_found", key=key, matched=matched,
                           note="identifier exists in the official text; content not verified")
        return _result(location, fld, reference, "parent_identifier_found", key=key, matched=matched,
                       note="cited below the level of the official list; parent exists; "
                            "content not verified")

    # A framework without a clause list (named in the reference or inherited
    # from the parent), or the loose alias heuristic for mapped frameworks.
    if (any(k in mapped_keys for k in named)
            or (not named and (_names_mapped_framework(reference, aliases)
                               or _names_mapped_framework(parent_name, aliases)))):
        return _result(location, fld, reference, "framework_not_covered",
                       key=next((k for k in named if k in mapped_keys), None),
                       note="no official clause list for this framework yet; reference not checked")
    return _result(location, fld, reference, "unmapped_framework",
                   note="names no framework in the mapped set")


def check_references(
    report: "ComplianceReport",
    mapping: "MappingResult",
    clause_lists: Optional[Dict[str, ClauseList]] = None,
) -> List[ReferenceCheckResult]:
    """Check every ``requirement_source`` and ``applicable_sections`` entry.

    Returns one result per reference, all with status "unverified".
    """
    lists = CLAUSE_LISTS if clause_lists is None else clause_lists
    aliases = mapped_aliases(mapping)
    mapped_keys = {m.key for m in mapping.framework_matches}
    out: List[ReferenceCheckResult] = []

    for fw in report.framework_assessments:
        out.extend(
            check_reference(ctrl.control_id, "requirement_source", ctrl.requirement_source,
                            fw.framework_name, mapped_keys, aliases, lists)
            for ctrl in fw.control_objectives
        )
    for reg in report.mandatory_regulations:
        out.extend(
            check_reference(f"{reg.regulation_name} (regulation)", "applicable_sections", section,
                            reg.regulation_name, mapped_keys, aliases, lists)
            for section in reg.applicable_sections
        )
    return out
