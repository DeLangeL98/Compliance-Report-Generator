"""
Compare clause locators found in a reference with the official clause lists.

``parse_locators`` pulls article / paragraph / section / control locators out
of free text such as "GDPR Art. 32(1)(b)" or "45 CFR 164.312(a)(2)(iv)".
``match_locators`` looks each one up in the clause lists of the candidate
frameworks (``saaf/knowledge/clauses.py``).

A hit proves only that the identifier EXISTS in the official text. Nothing in
this module reads clause wording, so it cannot tell whether a clause says what
a model claims.

Matching rule (decision on issue #7): sub-paragraphs are accepted whenever the
parent identifier exists. A sub-paragraph is only rejected at a level where the
list enumerates the siblings (e.g. the list holds art:32(1)..art:32(4), so
art:32(7) is rejected, while art:32(1)(b) is accepted because (b) is below the
listed level).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from saaf.knowledge.clauses import LOCATOR_ALIASES, ClauseList, Instrument, instruments_named

# ---------------------------------------------------------------------------
# Locator parsing
# ---------------------------------------------------------------------------

_SUBS = r"(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*"
_SUB_ITEM = re.compile(r"\(\s*([0-9a-z]{1,4})\s*\)", re.IGNORECASE)
_SEP = r"(?:\s*(?:,|;|&|\band\b|\bor\b|\bto\b|–|—|-)\s*)"

_NUMBER = {
    "art": r"\d+[a-z]{0,3}",
    "sch": r"\d+[a-z]{0,3}",
    "sec": r"\d+(?:\.\d+)*[a-z]{0,3}",
}

# keyword (anchors a list of numbers) -> locator kind
_KEYWORDS = (
    ("art", r"\b(?:articles?|arts?)\b\.?\s*"),
    ("sch", r"\b(?:schedules?|sch)\b\.?\s*"),
    # US Code / CFR citations first, so "45 CFR 164.312" is not read as a bare number
    ("sec", r"\b\d+\s*u\.?\s?s\.?\s?c\.?\s*(?:§+\s*)?"),
    ("sec", r"\b\d+\s*c\.?\s?f\.?\s?r\.?\s*(?:part\s+|§+\s*)?"),
    ("sec", r"(?:\bsections?\b|\bsecs?\b\.?|\bss\.|\bs\.|§§?)\s*"),
)


@dataclass(frozen=True)
class Locator:
    kind: str  # art | recital | annex | sec | sch | ctrl | cat | sub
    number: str  # as written, e.g. "32", "45a", "164.312", "AC-2", "GV.OC-01"
    subs: Tuple[str, ...] = ()
    raw: str = ""
    # Pattern-derived (no "Article"/"Section" keyword): dropped, not rejected,
    # when the framework has no identifiers of this kind.
    weak: bool = False

    def display(self) -> str:
        return self.number + "".join(f"({s})" for s in self.subs)


def _subs_of(text: str) -> Tuple[str, ...]:
    return tuple(m.lower() for m in _SUB_ITEM.findall(text or ""))


def _number_list(kind: str, text: str, pos: int) -> Tuple[List[Locator], int]:
    """Parse "5, 6 and 32" / "12–22" starting at ``pos``; return locators and end."""
    item = re.compile(rf"({_NUMBER[kind]})({_SUBS})", re.IGNORECASE)
    out: List[Locator] = []
    m = item.match(text, pos)
    if not m:
        return out, pos
    end = m.end()
    out.append(Locator(kind, m.group(1).lower(), _subs_of(m.group(2)), m.group(0).strip()))
    sep = re.compile(_SEP, re.IGNORECASE)
    while True:
        s = sep.match(text, end)
        if not s:
            break
        m2 = item.match(text, s.end())
        if not m2:
            break
        prev = out[-1]
        is_range = bool(re.fullmatch(r"\s*(?:to|–|—|-)\s*", s.group(0)))
        if (is_range and kind != "sec" and prev.number.isdigit() and not prev.subs
                and m2.group(1).isdigit() and not _subs_of(m2.group(2))
                and 0 < int(m2.group(1)) - int(prev.number) <= 300):
            out.extend(Locator(kind, str(n), (), str(n))
                       for n in range(int(prev.number) + 1, int(m2.group(1)) + 1))
        else:
            out.append(Locator(kind, m2.group(1).lower(), _subs_of(m2.group(2)),
                               m2.group(0).strip()))
        end = m2.end()
    return out, end


def parse_locators(text: str) -> List[Locator]:
    """Extract clause locators from ``text`` (kinds only; no lookup)."""
    found: List[Locator] = []
    consumed: List[Tuple[int, int]] = []

    def free(start: int) -> bool:
        return not any(a <= start < b for a, b in consumed)

    for kind, pattern in _KEYWORDS:
        for km in re.finditer(pattern, text, re.IGNORECASE):
            if not free(km.start()):
                continue
            locs, end = _number_list(kind, text, km.end())
            if locs:
                found.extend(locs)
                consumed.append((km.start(), end))

    for m in re.finditer(r"\brecitals?\b\s*(\d+(?:\s*(?:,|and|&)\s*\d+)*)", text, re.IGNORECASE):
        found.extend(Locator("recital", n, (), n) for n in re.findall(r"\d+", m.group(1)))
    found.extend(
        Locator("annex", m.group(1).upper(), (), m.group(0))
        for m in re.finditer(r"\bannex(?:es)?\s+([ivxlc]+|[a-z])\b", text, re.IGNORECASE)
    )

    # NIST CSF 2.0 subcategory / category, e.g. GV.OC-01, GV.OC
    found.extend(
        Locator("sub", f"{m.group(1)}.{m.group(2)}-{m.group(3)}".upper(), (), m.group(0), True)
        for m in re.finditer(r"\b([a-z]{2})\.([a-z]{2})-(\d{1,2})\b", text, re.IGNORECASE)
    )
    found.extend(
        Locator("cat", f"{m.group(1)}.{m.group(2)}".upper(), (), m.group(0), True)
        for m in re.finditer(r"\b([a-z]{2})\.([a-z]{2})\b(?!-\d)", text, re.IGNORECASE)
    )
    # NIST SP 800-53 control / enhancement, e.g. AC-2, AC-2(1), AC-2 (1)
    for m in re.finditer(r"(?<![\w.])([a-z]{2})\s?-\s?(\d{1,2})(?:\s?\(\s?(\d{1,2})\s?\))?", text, re.IGNORECASE):
        subs = (m.group(3),) if m.group(3) else ()
        found.append(Locator("ctrl", f"{m.group(1)}-{int(m.group(2))}".upper(), subs, m.group(0), True))

    if not any(loc.kind == "sec" for loc in found):
        # Bare dotted number such as "164.312(a)(1)" or "1798.100"
        found.extend(
            Locator("sec", m.group(1).lower(), _subs_of(m.group(2)), m.group(0), True)
            for m in re.finditer(rf"(?<![\d.\w])(\d{{2,4}}\.\d{{1,5}}[a-z]?)({_SUBS})", text, re.IGNORECASE)
        )
    return found


# ---------------------------------------------------------------------------
# Matching against clause lists
# ---------------------------------------------------------------------------

FOUND_EXACT = "exact"
FOUND_PARENT = "parent"
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class LocatorMatch:
    locator: Locator
    outcome: str  # exact | parent | not_found
    identifier: Optional[str] = None  # canonical identifier matched (deepest listed)
    detail: str = ""


class _Index:
    """Case-insensitive lookup + 'has listed children' index for one instrument."""

    def __init__(self, inst: Instrument) -> None:
        self.lower: Dict[str, str] = {i.lower(): i for i in inst.identifiers}
        self.parents: Set[str] = set()
        for ident in self.lower:
            if ident.endswith(")") and "(" in ident:
                parent = ident[: ident.rindex("(")]
                if parent in self.lower:
                    self.parents.add(parent)


_INDEX_CACHE: Dict[Tuple[str, str, str, int], _Index] = {}


def _index(framework_key: str, inst: Instrument) -> _Index:
    key = (framework_key, inst.code, inst.version, len(inst.identifiers))
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = _Index(inst)
    return _INDEX_CACHE[key]


def _prefixes(kind: str) -> Tuple[str, ...]:
    return ("sec", "cfr") if kind == "sec" else (kind,)


def _canonical_number(prefix: str, loc: Locator) -> str:
    if prefix in ("ctrl", "sub", "cat", "annex"):
        return loc.number.upper()
    return loc.number.lower()


def _match_in_instrument(idx: _Index, prefix: str, loc: Locator) -> LocatorMatch:
    base = f"{prefix}:{_canonical_number(prefix, loc)}".lower()
    if base not in idx.lower:
        return LocatorMatch(loc, NOT_FOUND, None, "not in the official clause list")
    cur = base
    for sub in loc.subs:
        nxt = f"{cur}({sub.lower()})"
        if nxt in idx.lower:
            cur = nxt
            continue
        if cur in idx.parents:
            return LocatorMatch(
                loc, NOT_FOUND, idx.lower[cur],
                f"({sub}) is not listed under {idx.lower[cur].split(':', 1)[1]}",
            )
        return LocatorMatch(loc, FOUND_PARENT, idx.lower[cur],
                            f"finer than the official list; accepted because {idx.lower[cur].split(':', 1)[1]} exists")
    return LocatorMatch(loc, FOUND_EXACT, idx.lower[cur])


def match_locators(
    locators: Sequence[Locator], candidates: Iterable[ClauseList], context_text: str
) -> List[LocatorMatch]:
    """Look every locator up in the candidate frameworks' instruments."""
    candidates = list(candidates)
    pool: List[Tuple[ClauseList, Instrument]] = []
    for cl in candidates:
        named = set(instruments_named(cl.framework_key, context_text))
        insts = [i for i in cl.instruments if not named or i.code in named] or list(cl.instruments)
        pool.extend((cl, i) for i in insts)

    results: List[LocatorMatch] = []
    for loc in locators:
        best: Optional[LocatorMatch] = None
        applicable = False
        for cl, inst in pool:
            for prefix in _prefixes(loc.kind):
                if prefix not in inst.kinds:
                    continue
                applicable = True
                idx = _index(cl.framework_key, inst)
                m = _match_in_instrument(idx, prefix, loc)
                alias = LOCATOR_ALIASES.get(cl.framework_key, {}).get(loc.number)
                if m.outcome == NOT_FOUND and alias and prefix == "sec":
                    m2 = _match_in_instrument(
                        idx, prefix, Locator(loc.kind, alias, loc.subs, loc.raw, loc.weak))
                    if m2.outcome != NOT_FOUND:
                        m = LocatorMatch(loc, m2.outcome, m2.identifier,
                                         f"public-law section {loc.number} read as US Code {alias}")
                if best is None or _rank(m) > _rank(best):
                    best = m
        if not applicable and loc.weak:
            continue
        if not applicable:
            best = LocatorMatch(loc, NOT_FOUND, None,
                                f"{loc.kind} references do not exist in this framework's official text")
        results.append(best)  # type: ignore[arg-type]
    return results


def _rank(m: LocatorMatch) -> int:
    return {FOUND_EXACT: 2, FOUND_PARENT: 1, NOT_FOUND: 0}[m.outcome]
