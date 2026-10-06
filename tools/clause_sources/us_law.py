"""Extract valid clause identifiers for HIPAA and GLBA (US law).

Run from the repository root::

    python3 -I tools/clause_sources/us_law.py [--cache DIR]

Writes ``saaf/knowledge/clause_data/HIPAA.json`` and ``GLBA.json``.

Sources (all official, parsed deterministically; nothing is typed in by hand):

* eCFR versioner API (https://www.ecfr.gov/api/versioner/v1/...): the ``full``
  XML of 45 CFR 160, 45 CFR 164, 16 CFR 314 and 12 CFR 1016, cross-checked
  against the ``structure`` JSON of the same title (section list, reserved flag).
* GPO govinfo publication of the United States Code, 15 U.S.C. chapter 94
  (the OLRC Code site uscode.house.gov was returning "Under Maintenance" when
  this was written; govinfo publishes the same Office of the Law Revision
  Counsel text as the official "United States Code, 2024 Edition").

Paragraph hierarchy (eCFR XML is flat ``<P>`` elements whose text begins with
markers such as ``(a)(1)`` or ``(iv)``) is rebuilt from nesting context by
:class:`ParagraphResolver`: a marker is accepted only as the *first child* of
the current paragraph or as the *successor of a paragraph already open*; the
"(i)/(v)/(x)" letter-vs-roman ambiguity is resolved by that rule (and, if still
ambiguous, by one-paragraph look-ahead). Anything that cannot be resolved
raises, and the section falls back to section level (reported).
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import USER_AGENT, fetch, write_clause_file  # noqa: E402

RETRIEVED_ON = "2026-10-06"
METHOD = "tools/clause_sources/us_law.py"
ECFR = "https://www.ecfr.gov/api/versioner/v1"

# --------------------------------------------------------------------------- paragraph markers

ROMAN = [("m", 1000), ("cm", 900), ("d", 500), ("cd", 400), ("c", 100), ("xc", 90),
         ("l", 50), ("xl", 40), ("x", 10), ("ix", 9), ("v", 5), ("iv", 4), ("i", 1)]


def to_roman(n: int) -> str:
    out = ""
    for sym, val in ROMAN:
        while n >= val:
            out += sym
            n -= val
    return out


ROMAN_LOWER = {to_roman(n) for n in range(1, 40)}
ROMAN_UPPER = {r.upper() for r in ROMAN_LOWER}

# depth -> kind. CFR/USC nesting: (a) (1) (i) (A) (1)-roman-upper ... ; eCFR italicises
# deeper levels but the italics are lost in plain text, so depths >= 5 are by type only.
KINDS = ["alpha", "digit", "roman", "ALPHA", "ROMAN", "digit", "alpha"]
MAX_DEPTH = len(KINDS)


def kind_depths(m: str) -> list[int]:
    out = []
    for d, k in enumerate(KINDS):
        if k == "alpha" and m.islower() and m.isalpha() and len(set(m)) == 1:
            out.append(d)
        elif k == "digit" and m.isdigit():
            out.append(d)
        elif k == "roman" and m in ROMAN_LOWER:
            out.append(d)
        elif k == "ALPHA" and m.isupper() and m.isalpha() and len(set(m)) == 1:
            out.append(d)
        elif k == "ROMAN" and m in ROMAN_UPPER:
            out.append(d)
    return out


def successor(m: str, depth: int) -> str:
    k = KINDS[depth]
    if k == "digit":
        return str(int(m) + 1)
    if k == "roman":
        for n in range(1, 60):
            if to_roman(n) == m:
                return to_roman(n + 1)
        return "?"
    if k == "ROMAN":
        return successor(m.lower(), 2).upper()
    # alpha / ALPHA: a..z, aa, bb, ... zz, aaa
    c = m[0]
    if c in "zZ":
        return c.lower() * (len(m) + 1) if m.islower() else c * (len(m) + 1)
    nxt = chr(ord(c) + 1)
    return nxt * len(m)


def first_of(depth: int) -> set[str]:
    k = KINDS[depth]
    return {"digit": {"1"}, "roman": {"i"}, "ROMAN": {"I"},
            "alpha": {"a"}, "ALPHA": {"A"}}[k]


class ParagraphError(Exception):
    pass


class ParagraphResolver:
    """Rebuild paragraph paths for one section from its ordered marker chains."""

    def __init__(self) -> None:
        self.stack: list[str] = []

    def _candidates(self, m: str, stack: list[str]) -> list[list[str]]:
        res = []
        for d in kind_depths(m):
            if d == len(stack) and m in first_of(d):
                res.append(stack + [m])
            elif d < len(stack) and m == successor(stack[d], d):
                res.append(stack[:d] + [m])
        return res

    def feed(self, chain: list[str], nxt: str | None) -> list[str]:
        cands = self._candidates(chain[0], self.stack)
        if len(cands) > 1 and nxt:
            ok = [c for c in cands if self._candidates(nxt, c)]
            if len(ok) >= 1:
                cands = ok
        if len(cands) != 1:
            raise ParagraphError(
                f"marker {chain!r} after {self.stack!r}: {len(cands)} candidates")
        stack = cands[0]
        for m in chain[1:]:
            if len(stack) >= MAX_DEPTH or m not in first_of(len(stack)):
                raise ParagraphError(f"chain {chain!r} after {self.stack!r}: bad child {m!r}")
            stack = stack + [m]
        self.stack = stack
        return stack


_SEG = re.compile(r"^((?:\([A-Za-z0-9]+\))+)\s*(?:\x01[^\x02]*\x02\s*)?")
_MARK = re.compile(r"\(([A-Za-z0-9]+)\)")


def split_marker(text: str) -> tuple[list[list[str]], str] | None:
    """Leading marker chains of a paragraph, e.g. "(c) <I>Heading.</I> (1) Text" ->
    ([['c'], ['1']], 'Text'). Italic headings between chains are skipped."""
    t = text.strip()
    chains: list[list[str]] = []
    while True:
        m = _SEG.match(t)
        if not m:
            break
        chains.append(_MARK.findall(m.group(1)))
        t = t[m.end():]
    if not chains:
        return None
    return chains, t.replace("\x01", "").replace("\x02", "")


def is_reserved_text(rest: str) -> bool:
    return bool(re.match(r"^\s*\[(?:Reserved|Removed)\]", rest))


def paragraph_ids(section_id: str, paragraphs: list[str]) -> tuple[list[str], list[str]]:
    """Return (identifiers, problems) for one section.

    ``section_id`` is e.g. ``164.312``. Falls back to ``[section_id]`` plus a
    problem string when the hierarchy cannot be reconstructed reliably.
    """
    items = []  # (chain, rest)
    for t in paragraphs:
        sm = split_marker(t)
        if sm:
            items.append(sm)
    res = ParagraphResolver()
    ids: list[str] = []
    try:
        for i, (chains, rest) in enumerate(items):
            nxt = items[i + 1][0][0][0] if i + 1 < len(items) else None
            opened = []
            for j, chain in enumerate(chains):
                look = nxt if j == len(chains) - 1 else chains[j + 1][0]
                opened.append((res.feed(chain, look), len(chain)))
            if is_reserved_text(rest):
                continue
            # emit every level opened by this P (a chain opens several levels)
            for stack, n in opened:
                for k in range(len(stack) - n + 1, len(stack) + 1):
                    ids.append("cfr:" + section_id + "".join(f"({x})" for x in stack[:k]))
    except ParagraphError as exc:
        return [], [f"{section_id}: {exc}"]
    return ids, []


# --------------------------------------------------------------------------- eCFR

def ecfr_get(url: str, cache: Path | None) -> bytes:
    if cache:
        p = cache / re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/v1/")[-1])
        if p.exists():
            return p.read_bytes()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"failed to fetch {url}: {last}")
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return data


def title_dates(title: int, cache: Path | None) -> dict:
    d = json.loads(ecfr_get(f"{ECFR}/titles.json", None))
    return next(t for t in d["titles"] if t["number"] == title)


def structure_sections(title: int, issue_date: str, part: str, cache: Path | None):
    """Section identifiers of ``part`` from the structure endpoint -> {id: reserved}."""
    url = f"{ECFR}/structure/{issue_date}/title-{title}.json"
    root = json.loads(ecfr_get(url, cache))
    out: dict[str, bool] = {}

    def walk(n, in_part):
        if n.get("type") == "part":
            in_part = n.get("identifier") == part
        if in_part and n.get("type") == "section":
            out[n["identifier"]] = bool(n.get("reserved"))
        for c in n.get("children") or []:
            walk(c, in_part)

    walk(root, False)
    return out, url


def ptext(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def ptext_marked(el: ET.Element) -> str:
    """Paragraph text with <I> italics wrapped in \\x01..\\x02 (headings vs markers)."""
    out = [el.text or ""]
    for c in el:
        inner = "".join(c.itertext())
        out.append(f"\x01{inner}\x02" if c.tag == "I" else inner)
        out.append(c.tail or "")
    t = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\(\x01([A-Za-z0-9]+)\x02\)", r"(\1)", t)


def parse_ecfr_part(title: int, part: str, cache: Path | None) -> dict:
    dates = title_dates(title, cache)
    issue = dates["latest_issue_date"]
    url = f"{ECFR}/full/{issue}/title-{title}.xml?part={part}"
    xml = ecfr_get(url, cache)
    root = ET.fromstring(xml)
    struct, struct_url = structure_sections(title, issue, part, cache)

    ids: list[str] = []
    problems: list[str] = []
    sections_listed: list[str] = []
    skipped_reserved: list[str] = []
    for div in root.iter("DIV8"):
        n = div.get("N", "")
        head = ptext(div.find("HEAD")) if div.find("HEAD") is not None else ""
        if div.get("TYPE") != "SECTION":
            continue
        if re.search(r"\[(Reserved|Removed)\]", head) or not re.fullmatch(r"\d+\.\d+", n):
            skipped_reserved.append(f"{n} {head}")
            continue
        sections_listed.append(n)
        ids.append(f"cfr:{n}")
        paras = [ptext_marked(c) for c in div if c.tag in ("P", "FP")]
        pids, probs = paragraph_ids(n, paras)
        ids.extend(pids)
        problems.extend(probs)

    # ---- sanity checks
    assert len(set(sections_listed)) == len(sections_listed), "duplicate sections"
    struct_live = {k for k, v in struct.items() if not v and re.fullmatch(r"\d+\.\d+", k)}
    only_xml = set(sections_listed) - struct_live
    only_struct = struct_live - set(sections_listed)
    assert not only_xml and not only_struct, (only_xml, only_struct)
    # the 'reserved' sections of the structure endpoint must not be in our list
    assert not (set(sections_listed) & {k for k, v in struct.items() if v})
    assert len(set(ids)) == len(ids), "duplicate identifiers"
    print(f"{title} CFR {part}: {len(sections_listed)} sections, {len(ids)} identifiers "
          f"({len(ids) - len(sections_listed)} paragraph-level); structure endpoint lists "
          f"{len(struct)} entries of which {len(struct) - len(struct_live)} reserved; "
          f"{len(skipped_reserved)} reserved/removed skipped; "
          f"{len(problems)} sections fell back to section level", file=sys.stderr)
    for p in problems:
        print("  fallback:", p, file=sys.stderr)
    return {"ids": ids, "url": url, "struct_url": struct_url, "dates": dates, "issue": issue,
            "problems": problems, "sections": sections_listed, "reserved": skipped_reserved}


def ecfr_instrument(code: str, title_txt: str, r: dict, title: int) -> dict:
    d = r["dates"]
    return {
        "code": code,
        "title": title_txt,
        "version": (f"eCFR current text, issue date {r['issue']} (up to date as of "
                    f"{d['up_to_date_as_of']}; title {title} last amended {d['latest_amended_on']})"),
        "source": r["url"],
        "retrieved_on": RETRIEVED_ON,
        "retrieval_method": METHOD,
        "identifiers": sorted(set(r["ids"])),
    }


# --------------------------------------------------------------------------- US Code (govinfo)

USC_URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title15/html/USCODE-2024-title15-chap94.htm"


def parse_usc(cache: Path | None) -> dict:
    if cache and (cache / "usc15ch94.htm").exists():
        raw = (cache / "usc15ch94.htm").read_bytes()
    else:
        raw = fetch(USC_URL)
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "usc15ch94.htm").write_bytes(raw)
    s = raw.decode("utf-8", errors="replace")
    # TOC (plain text at the top): "6801.Protection of ..."
    toc_secs = re.findall(r'content-left">(\d{4}[a-z]?)\.</div>',
                          s.split("<!-- field-start:head -->")[0])
    assert toc_secs, "no TOC found"
    through = sorted(set(re.findall(r"currentthrough:(\d{8})", s)))
    assert len(through) == 1, through

    secs = re.split(r'(?=<h3 class="section-head">)', s)[1:]
    ids: list[str] = []
    credits: dict[str, str] = {}
    listed: list[str] = []
    problems: list[str] = []
    for blk in secs:
        mh = re.match(r'<h3 class="section-head">&sect;(\d+[a-z]?)\.\s*(.*?)</h3>', blk, re.S)
        if not mh:
            continue
        num = mh.group(1)
        head = html.unescape(mh.group(2))
        if "[Repealed" in head or "[Reserved" in head or "[Omitted" in head:
            continue
        listed.append(num)
        ids.append(f"sec:{num}")
        body = blk.split("<!-- field-start:statute -->")[1].split("<!-- field-end:statute -->")[0]
        mc = re.search(r'<p class="source-credit">(.*?)</p>', blk, re.S)
        credits[num] = html.unescape(re.sub(r"<[^>]*>", "", mc.group(1))) if mc else ""
        # paragraph-level: h4.subsection-head "(a) Heading" and p.statutory-body*(N em) "(1) text"
        paras = []
        depth_by_text = {}
        for m in re.finditer(
                r'<(h4 class="subsection-head"|p class="statutory-body(?:-(\d)em)?")>(.*?)</(?:h4|p)>',
                body, re.S):
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", m.group(3)))).strip()
            paras.append(t)
            sm = split_marker(t)
            if sm:
                depth_by_text[t] = (0 if m.group(1).startswith("h4") else int(m.group(2) or 0))
        # drop "(a) Heading" / "(a) text" duplicates are harmless (same marker would repeat):
        # an h4 "(a) Heading" is followed by body paragraphs without marker, so no repeat.
        pids, probs = paragraph_ids(num, paras)
        if probs:
            problems.extend(probs)
            continue
        for pid in pids:
            ids.append("sec:" + pid[len("cfr:"):])
    sub1 = [n for n in listed if 6801 <= int(re.match(r"\d+", n).group(0)) <= 6809]
    sub2 = [n for n in listed if 6821 <= int(re.match(r"\d+", n).group(0)) <= 6827]
    assert listed == toc_secs, (listed, toc_secs)
    assert sub1 == [str(n) for n in range(6801, 6810)], sub1
    assert sub2 == [str(n) for n in range(6821, 6828)], sub2
    assert len(set(ids)) == len(ids)
    edition = re.search(r"United States Code, (\d{4} Edition)", html.unescape(s))
    print(f"15 USC ch.94: {len(listed)} sections, {len(ids)} identifiers; problems={problems}",
          file=sys.stderr)
    return {"ids": ids, "credits": credits, "edition": edition.group(1) if edition else "?",
            "through": f"{through[0][:4]}-{through[0][4:6]}-{through[0][6:]}",
            "problems": problems}


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, help="directory for downloaded sources (outside the repo)")
    ap.add_argument("--dump-subtree", default="45:164:164.312",
                    help="title:part:section whose derived tree is printed")
    a = ap.parse_args()
    cache = a.cache

    p160 = parse_ecfr_part(45, "160", cache)
    p164 = parse_ecfr_part(45, "164", cache)
    sec = "cfr:164.312"
    print("\nDerived subtree of 45 CFR 164.312:", file=sys.stderr)
    for i in sorted(p164["ids"]):
        if i == sec or i.startswith(sec + "("):
            print("  " + i, file=sys.stderr)

    hipaa_rationale = (
        "Paragraph level (cfr-paragraph). The HIPAA Security Rule is audited by standard and "
        "implementation specification (e.g. 164.308(a)(1)(ii)(A) risk analysis, 164.312(a)(2)(iv) "
        "encryption), and the Privacy and Breach Notification Rules by their lettered paragraphs "
        "(e.g. 164.404(b), 164.502(a)), so every section and every numbered/lettered paragraph "
        "of 45 CFR Parts 160 and 164 is listed, reconstructed from the eCFR XML nesting. "
        "Reserved and removed sections and paragraphs are not listed. Sections whose paragraph "
        "hierarchy could not be reconstructed reliably are listed at section level only. "
        "Out of scope: 45 CFR Part 162 (administrative simplification transactions and code "
        "sets) and the HITECH Act statute (Pub. L. 111-5, title XIII), whose breach and "
        "security requirements are implemented by Parts 160/164 and are cited through those parts."
    )
    if p160["problems"] or p164["problems"]:
        hipaa_rationale += (" Section-level fallback sections: " + "; ".join(
            sorted({p.split(":")[0] for p in p160["problems"] + p164["problems"]})) + ".")
    write_clause_file("HIPAA", "cfr-paragraph", hipaa_rationale, [
        ecfr_instrument("HIPAA_PART_160", "45 CFR Part 160 - General Administrative Requirements",
                        p160, 45),
        ecfr_instrument("HIPAA_PART_164",
                        "45 CFR Part 164 - Security and Privacy (incl. Breach Notification)",
                        p164, 45),
    ])

    p314 = parse_ecfr_part(16, "314", cache)
    p1016 = parse_ecfr_part(12, "1016", cache)
    usc = parse_usc(cache)
    glba_rationale = (
        "Mixed, as specific as an auditor can test. The statute (15 U.S.C. 6801-6809, 6821-6827) "
        "is listed by section and by subsection/paragraph as numbered in the Code (e.g. sec:6801(b)), "
        "which is the level at which the Act is cited. The FTC Safeguards Rule (16 CFR Part 314) and "
        "Regulation P (12 CFR Part 1016) are listed to paragraph level (e.g. cfr:314.4(c)(1) "
        "encryption/MFA requirements, cfr:1016.9 delivery of notices), reconstructed from the eCFR "
        "XML nesting. Omitted: 16 CFR Part 313 (privacy rule for motor vehicle dealers only) and "
        "the Pub. L. 106-102 title V section numbers (501-509) as such; the Code section numbers "
        "(6801-6809) are used."
    )
    probs = p314["problems"] + p1016["problems"] + usc["problems"]
    if probs:
        glba_rationale += (" Section-level fallback (paragraph hierarchy not reliably derivable): "
                           + "; ".join(sorted({p.split(":")[0] for p in probs})) + ".")
    write_clause_file("GLBA", "cfr-paragraph", glba_rationale, [
        {"code": "GLBA_USC",
         "title": "15 U.S.C. chapter 94, subchapters I and II (Gramm-Leach-Bliley Act title V)",
         "version": f"United States Code, {usc['edition']} (GPO govinfo publication of the OLRC Code), "
                    f"current through {usc['through']}",
         "source": USC_URL, "retrieved_on": RETRIEVED_ON, "retrieval_method": METHOD,
         "identifiers": usc["ids"]},
        ecfr_instrument("GLBA_SAFEGUARDS",
                        "16 CFR Part 314 - Standards for Safeguarding Customer Information "
                        "(FTC Safeguards Rule)", p314, 16),
        ecfr_instrument("GLBA_REG_P",
                        "12 CFR Part 1016 - Privacy of Consumer Financial Information (Regulation P)",
                        p1016, 12),
    ])
    print("\nPub. L. 106-102 title V -> U.S.C. source credits:", file=sys.stderr)
    for k, v in sorted(usc["credits"].items()):
        print(f"  {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
