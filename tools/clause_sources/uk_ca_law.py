"""Extract valid clause identifiers for the UK GDPR / DPA 2018 and the CCPA/CPRA.

Writes (via ``common.write_clause_file``):

* ``UK_GDPR.json``  - instruments ``UK_GDPR`` (legislation.gov.uk /eur/2016/679)
  and ``DPA_2018`` (legislation.gov.uk /ukpga/2018/12), both "latest revised".
* ``CCPA_CPRA.json`` - instrument ``CCPA_STATUTE`` (California Civil Code
  Title 1.81.5, ss. 1798.100 - 1798.199.100) from the Legislative Counsel's
  official bulk data (downloads.leginfo.legislature.ca.gov).

Run from the repository root:  ``python3 -I tools/clause_sources/uk_ca_law.py``
(stdlib only). Every identifier is parsed from the fetched official source;
nothing is typed in by hand. Downloaded content is treated as untrusted data:
it is parsed, never executed.

UK method: the official XML (``/data.xml`` = the "latest revised" text, and
``/contents/data.xml`` = the table of contents) is parsed. Identifiers come
from each provision's ``DocumentURI`` (e.g. ``.../article/45A``,
``.../section/119A``), not from the printed number text, which contains
change-tracking wrappers. A provision is excluded when it or any ancestor
carries ``Status="Repealed"`` or ``Status="Prospective"`` (the source's own
deterministic marker). Paragraphs repealed *inside* a still-live article/section
carry no attribute (only ". . . ." text); they are kept and counted.

California method: ``pubinfo_2025.zip`` is the Legislative Counsel's full dump
for the 2025-26 session. It is ~1.2 GB, so the zip is read with HTTP Range
requests and only the three small ``LAW_*_TBL.dat`` members are fetched. Column
order / delimiters come from the vendor's own ``pubinfo_load.zip`` loader
(``law_section_tbl.sql``: tab separated, optionally enclosed by a backtick).
The leginfo.legislature.ca.gov web pages sit behind a Cloudflare challenge and
are NOT used.
"""

from __future__ import annotations

import io
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # needed under ``python -I``
import common  # noqa: E402
from common import _IDENT, USER_AGENT, fetch, write_clause_file  # noqa: E402

RETRIEVED_ON = "2026-10-06"
METHOD = "tools/clause_sources/uk_ca_law.py"
LEG = "https://www.legislation.gov.uk"
EXCLUDED_STATUS = {"Repealed", "Prospective"}
NS = "{http://www.legislation.gov.uk/namespaces/legislation}"
DC_MODIFIED = "{http://purl.org/dc/elements/1.1/}modified"


EXCLUDE_DOT_STUBS = False  # True: also drop provisions whose whole text is ". . . ." (un-flagged omissions)


def natural_key(identifier: str) -> list:
    """common.natural_key can compare int with str for labels like (a1) vs (1); make it total."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|[A-Za-z]+|\W", identifier)]


common.natural_key = natural_key  # write_clause_file looks the name up in common's globals


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"SANITY CHECK FAILED: {msg}")
    print(f"  ok: {msg}", file=sys.stderr)


def local(e) -> str:
    return e.tag.split("}")[-1] if isinstance(e.tag, str) else ""


# ---------------------------------------------------------------- UK


class UKDoc:
    def __init__(self, path: str):
        self.url = f"{LEG}{path}/data.xml"
        self.contents_url = f"{LEG}{path}/contents/data.xml"
        self.path = path
        raw = fetch(self.url)
        self.root = ET.fromstring(raw)
        self.contents = ET.fromstring(fetch(self.contents_url))
        self.parent = {c: p for p in self.root.iter() for c in p}
        self.modified = next(e.text for e in self.root.iter(DC_MODIFIED))
        self.restrict_start = self.root.get("RestrictStartDate")
        self.n_prov = int(self.root.get("NumberOfProvisions"))
        self.unapplied = Counter(
            e.get("Type") for e in self.root.iter() if local(e) == "UnappliedEffect"
        )

    def excluded(self, e) -> bool:
        while e is not None:
            if e.get("Status") in EXCLUDED_STATUS:
                return True
            e = self.parent.get(e)
        return False

    def elements(self, tag: str, uri_re: re.Pattern):
        """(match, element, excluded) for elements ``tag`` whose DocumentURI matches."""
        for e in self.root.iter():
            if local(e) != tag:
                continue
            m = uri_re.match(e.get("DocumentURI", ""))
            if m:
                yield m, e, self.excluded(e)

    def version(self, what: str) -> str:
        return (
            f"{what}, latest revised version as served by /data.xml with no date "
            f"in the URL (document modified {self.modified}; root "
            f"RestrictStartDate {self.restrict_start}); fetched {RETRIEVED_ON}"
        )


def placeholder(e) -> bool:
    """True for ``. . . .`` / 'Repealed' stubs left by an un-flagged repeal."""
    txt = "".join(e.itertext())
    txt = re.sub(r"^\s*[0-9A-Za-z]+\.?\s*(?:\([0-9A-Za-z]+\))?", "", txt, count=1)
    return not re.sub(r"[\s.…\-]|(?i:repealed|omitted)", "", txt)


def lc(s: str) -> str:
    return s.rstrip(".").lower()


def split_grammar(ids: list[str]) -> tuple[list[str], list[str]]:
    ok = [i for i in ids if _IDENT.match(i)]
    return ok, [i for i in ids if not _IDENT.match(i)]


def uk_gdpr() -> dict:
    d = UKDoc("/eur/2016/679")
    base = re.escape("http://www.legislation.gov.uk/eur/2016/679")
    raw: list[str] = []  # raw list (duplicates would be visible)
    art_nums, n_dots_p2, repealed_arts = [], 0, []
    for m, _e, ex in d.elements("P1", re.compile(base + r"/article/([0-9]+[A-Za-z]*)\.?$")):
        a = lc(m.group(1))
        if ex:
            repealed_arts.append(a)
            continue
        raw.append(f"art:{a}")
        art_nums.append(a)
    for m, e, ex in d.elements("P2", re.compile(base + r"/article/([0-9]+[A-Za-z]*)\.?/([0-9]+[A-Za-z]*)$")):
        if ex:
            continue
        if placeholder(e):
            n_dots_p2 += 1
        raw.append(f"art:{lc(m.group(1))}({lc(m.group(2))})")
    # recitals: Division elements inside the preamble, number text "(n)"
    rec = []
    for pre in d.root.iter():
        if local(pre) != "EUPreamble":
            continue
        for e in pre.iter():
            if local(e) == "Division" and not d.excluded(e):
                num = "".join(next(x for x in e if local(x) == "Number").itertext()).strip()
                mm = re.fullmatch(r"\((\d+)\)", num)
                uri_n = e.get("DocumentURI").rsplit("/", 1)[1]
                if not mm or uri_n != mm.group(1):
                    raise AssertionError(f"recital number mismatch: text {num!r} vs URI {uri_n}")
                rec.append(int(mm.group(1)))
    raw += [f"recital:{n}" for n in rec]

    # sanity checks
    print("UK GDPR:", file=sys.stderr)
    check(len(raw) == len(set(raw)), "no duplicate identifiers in raw list")
    nums = [int(re.match(r"\d+", a).group()) for a in art_nums]
    ctop = max(int(re.match(r"\d+", a).group()) for a in
               (m.group(1) for e in d.contents.iter() for m in [re.search(r"/article/([0-9]+[A-Za-z]*)\.?$", e.get("DocumentURI", ""))] if m))
    check(set(range(1, ctop + 1)) <= set(nums) | {int(re.match(r"\d+", a).group()) for a in repealed_arts},
          f"articles 1..{ctop} (highest in contents/data.xml) all present in source (live or repealed-marked)")
    check(sorted(rec) == list(range(1, max(rec) + 1)), f"recitals contiguous 1..{max(rec)}; printed number == URI number for each")
    annex_p1 = sum(1 for _ in d.elements("P1", re.compile(base + r"/annex/")))
    check(len(art_nums) + len(repealed_arts) + annex_p1 == d.n_prov,
          f"live+repealed articles ({len(art_nums)}+{len(repealed_arts)}) + annex P1 ({annex_p1}) "
          f"== root NumberOfProvisions {d.n_prov}")
    contents_arts = {
        lc(m.group(1))
        for e in d.contents.iter()
        for m in [re.search(r"/article/([0-9]+[A-Za-z]*)\.?$", e.get("DocumentURI", ""))]
        if m
    }
    check(contents_arts == set(art_nums) | set(repealed_arts),
          f"article set equals contents/data.xml article set ({len(contents_arts)})")
    ids, bad = split_grammar(raw)
    print(f"  repealed (Status) articles excluded: {sorted(repealed_arts, key=common.natural_key)}", file=sys.stderr)
    print(f"  identifiers outside the shared grammar, NOT written: {bad}", file=sys.stderr)
    print(f"  P2 paragraphs that are dots-only stubs (kept): {n_dots_p2}", file=sys.stderr)
    print(f"  annex provisions (amending annexes 1-2, not listed): {annex_p1}", file=sys.stderr)
    print(f"  UnappliedEffect: {dict(d.unapplied)}", file=sys.stderr)
    print(f"  articles={len(art_nums)} paragraphs={sum(1 for i in ids if i.startswith('art:') and '(' in i)} recitals={len(rec)}", file=sys.stderr)
    return dict(
        code="UK_GDPR",
        title="Regulation (EU) 2016/679 as retained and amended in UK law (UK GDPR)",
        version=d.version("UK GDPR, legislation.gov.uk /eur/2016/679 'latest revised'"),
        source=d.url,
        retrieved_on=RETRIEVED_ON,
        retrieval_method=METHOD,
        identifiers=ids,
    ), bad


def dpa() -> dict:
    d = UKDoc("/ukpga/2018/12")
    base = re.escape("http://www.legislation.gov.uk/ukpga/2018/12")
    raw: list[str] = []
    secs, rep_secs, sub_ct, stubs_secs = [], [], 0, []
    for m, e, ex in d.elements("P1", re.compile(base + r"/section/([0-9]+[A-Za-z]*)$")):
        s = lc(m.group(1))
        if ex:
            rep_secs.append(s)
            continue
        if placeholder(e):
            stubs_secs.append(s)
            if EXCLUDE_DOT_STUBS:
                continue
        raw.append(f"sec:{s}")
        secs.append(s)
    for m, _e, ex in d.elements("P2", re.compile(base + r"/section/([0-9]+[A-Za-z]*)/([0-9A-Za-z]+)$")):
        if not ex:
            raw.append(f"sec:{lc(m.group(1))}({lc(m.group(2))})")
            sub_ct += 1
    sch_paras, rep_paras, stub_paras = [], [], []
    for m, _e, ex in d.elements("Schedule", re.compile(base + r"/schedule/([0-9A-Za-z]+)$")):
        if not ex:
            raw.append(f"sch:{lc(m.group(1))}")
    for m, e, ex in d.elements("P1", re.compile(base + r"/schedule/([0-9A-Za-z]+)/paragraph/([0-9]+[A-Za-z]*)$")):
        ident = f"sch:{lc(m.group(1))}({lc(m.group(2))})"
        if ex:
            rep_paras.append(ident)
            continue
        if placeholder(e):
            stub_paras.append(ident)
        raw.append(ident)
        sch_paras.append(ident)

    print("DPA 2018:", file=sys.stderr)
    check(len(raw) == len(set(raw)), "no duplicate identifiers in raw list")
    live = {int(re.match(r"\d+", s).group()) for s in secs} | {int(re.match(r"\d+", s).group()) for s in rep_secs}
    stop = max(int(re.match(r"\d+", x).group()) for x in
               (m.group(1) for e in d.contents.iter() for m in [re.search(r"/section/([0-9]+[A-Za-z]*)$", e.get("DocumentURI", ""))] if m))
    check(set(range(1, stop + 1)) <= live, f"sections 1..{stop} (highest in contents/data.xml) all present in source")
    all_sch_p1 = sum(1 for _ in d.elements("P1", re.compile(base + r"/schedule/[^/]+/paragraph/[^/]+$")))
    all_sec_p1 = len(secs) + len(rep_secs)
    no_uri_p1 = sum(1 for e in d.root.iter() if local(e) == "P1" and not e.get("DocumentURI"))
    total_p1 = sum(1 for e in d.root.iter() if local(e) == "P1")
    check(total_p1 == d.n_prov and total_p1 == all_sec_p1 + all_sch_p1 + no_uri_p1,
          f"root NumberOfProvisions {d.n_prov} == all P1 elements ({total_p1}) = section P1 {all_sec_p1} + "
          f"schedule-paragraph P1 {all_sch_p1} + {no_uri_p1} P1 without DocumentURI (quoted amendment text, not listed)")
    # provision-bearing elements the root counter may include
    kinds = Counter(local(e) for e in d.root.iter()
                    if e.get("DocumentURI") and local(e) in {"Part", "Chapter", "Schedule", "P1", "Pblock"})
    print(f"  elements with a DocumentURI by tag: {dict(kinds)}", file=sys.stderr)
    # contents/data.xml cross-check
    cs = {m.group(1).lower() for e in d.contents.iter()
          for m in [re.search(r"/section/([0-9]+[A-Za-z]*)$", e.get("DocumentURI", ""))] if m}
    check(cs == {s for s in secs} | {s for s in rep_secs}, f"section set equals contents/data.xml section set ({len(cs)})")
    cp = {(m.group(1).lower(), m.group(2).lower()) for e in d.contents.iter()
          for m in [re.search(r"/schedule/([0-9A-Za-z]+)/paragraph/([0-9]+[A-Za-z]*)$", e.get("DocumentURI", ""))] if m}
    mine = {(re.match(r"sch:(\w+)\((\w+)\)", i).groups()) for i in sch_paras + rep_paras}
    check(cp == mine, f"schedule-paragraph set (live + repealed-marked) equals contents/data.xml set ({len(cp)})")
    print(f"  contents-only schedule paras: {sorted(cp - mine)[:10]}  body-only: {sorted(mine - cp)[:10]}", file=sys.stderr)
    ids, bad = split_grammar(raw)
    print(f"  excluded (Status Repealed/Prospective): sections={len(rep_secs)} schedule paragraphs={len(rep_paras)}", file=sys.stderr)
    print(f"  un-flagged dots-only P1 stubs kept: sections={stubs_secs} schedule paras={len(stub_paras)}", file=sys.stderr)
    print(f"  identifiers outside the shared grammar, NOT written: {bad}", file=sys.stderr)
    print(f"  UnappliedEffect: {dict(d.unapplied)}", file=sys.stderr)
    n_sch = sum(1 for i in ids if re.fullmatch(r"sch:\w+", i))
    print(f"  sections={len(secs)} subsections={sub_ct} schedules={n_sch} sch-paras={len(sch_paras)}", file=sys.stderr)
    return dict(
        code="DPA_2018",
        title="Data Protection Act 2018 (c. 12)",
        version=d.version("DPA 2018, legislation.gov.uk /ukpga/2018/12 'latest revised'"),
        source=d.url,
        retrieved_on=RETRIEVED_ON,
        retrieval_method=METHOD,
        identifiers=ids,
    ), bad


# ---------------------------------------------------------------- California


class RangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP Range requests (stdlib only)."""

    def __init__(self, url: str):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
            self.etag = r.headers.get("ETag")
            self.last_modified = r.headers.get("Last-Modified")
            assert r.headers.get("Accept-Ranges") == "bytes", "server does not support Range"

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(
            self.url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def dat_rows(text: str):
    """Rows of a pubinfo .dat file: tab separated, backtick-enclosed, NULL -> None."""
    for line in text.split("\n"):
        if line:
            yield [None if x == "NULL" else x.strip("`") for x in line.split("\t")]


def ccpa() -> dict:
    zip_url = "https://downloads.leginfo.legislature.ca.gov/pubinfo_2025.zip"
    rf = RangeFile(zip_url)
    z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 20))
    # column order from the vendor loader scripts (pubinfo_load.zip)
    load = zipfile.ZipFile(io.BytesIO(fetch("https://downloads.leginfo.legislature.ca.gov/pubinfo_load.zip")))
    def cols(sqlname: str) -> list[str]:
        sql = load.read(sqlname).decode("latin1")
        body = sql[sql.index("(\n"):sql.index("\n)")]
        return [c.strip().lstrip(",").strip() for c in body.split("\n")[1:] if c.strip()]
    sec_cols = cols("law_section_tbl.sql")
    toc_cols = cols("law_toc_sections_tbl.sql")
    print("California:", file=sys.stderr)
    check(sec_cols[:3] == ["ID", "LAW_CODE", "SECTION_NUM"], f"law_section_tbl columns from vendor loader: {sec_cols[:6]}...")
    sec_rows = [dict(zip(sec_cols, r, strict=False)) for r in dat_rows(z.read("LAW_SECTION_TBL.dat").decode("utf8"))]
    toc_rows = [dict(zip(toc_cols, r, strict=False)) for r in dat_rows(z.read("LAW_TOC_SECTIONS_TBL.dat").decode("utf8"))]
    # Title 1.81.5 (Division 3, Part 4) of the Civil Code
    mine = [r for r in sec_rows
            if r["LAW_CODE"] == "CIV" and r["DIVISION"] == "3." and r["TITLE"] == "1.81.5."
            and r["PART"] == "4." and r["ACTIVE_FLG"] == "Y"]
    nums = [r["SECTION_NUM"].rstrip(".") for r in mine]
    # cross-check with the TOC table: the title's node treepath is read from LAW_TOC_TBL.dat
    toc_tbl = list(dat_rows(z.read("LAW_TOC_TBL.dat").decode("utf8")))
    paths = [r[13] for r in toc_tbl if r[0] == "CIV" and r[1] == "3." and r[2] == "1.81.5." and r[3] == "4."]
    check(len(paths) == 1, f"exactly one LAW_TOC_TBL node for CIV Div 3 Title 1.81.5 Part 4 (treepath {paths})")
    heading = next(r[6] for r in toc_tbl if r[13] == paths[0])
    toc_nums = [r["SECTION_NUM"].rstrip(".") for r in toc_rows
                if r["LAW_CODE"] == "CIV" and r["NODE_TREEPATH"] == paths[0]]
    check(len(nums) == len(set(nums)), "no duplicate section numbers")
    check(sorted(nums) == sorted(toc_nums), f"LAW_SECTION_TBL and LAW_TOC_SECTIONS_TBL agree ({len(nums)} sections)")
    check(nums and all(re.fullmatch(r"1798\.\d+(\.\d+)?", n) for n in nums), "all numbers look like 1798.x[.y]")
    first = min(nums, key=common.natural_key)
    last = max(nums, key=common.natural_key)
    check((first, last) == ("1798.100", "1798.199.100"), f"range is 1798.100 .. 1798.199.100 as in the title heading: {heading!r}")
    ids = [f"sec:{n}" for n in nums]
    ids, bad = split_grammar(ids)
    check(not bad, "all identifiers fit the shared grammar")
    print(f"  sections={len(ids)}; zip Last-Modified {rf.last_modified}, ETag {rf.etag}", file=sys.stderr)
    return dict(
        code="CCPA_STATUTE",
        title="California Consumer Privacy Act of 2018 as amended by the CPRA (Cal. Civ. Code, Div. 3, Pt. 4, Title 1.81.5, ss. 1798.100-1798.199.100)",
        version=(f"Legislative Counsel pubinfo_2025.zip (2025-26 session full dump), LAW_SECTION_TBL.dat rows with "
                 f"ACTIVE_FLG=Y; zip Last-Modified {rf.last_modified}, ETag {rf.etag}; includes amendments through "
                 f"Stats. 2025 (e.g. s.1798.185 as amended by Stats. 2025, Ch. 67, effective 1 Jan 2026)"),
        source=zip_url,
        retrieved_on=RETRIEVED_ON,
        retrieval_method=METHOD,
        identifiers=ids,
    )


def main() -> None:
    gdpr, bad1 = uk_gdpr()
    dpa_inst, bad2 = dpa()
    write_clause_file(
        "UK_GDPR",
        "article-paragraph",
        "UK GDPR is listed at article level plus numbered paragraphs (art:N, art:N(P)) and recitals (recital:N; the UK "
        "text retains the 173 recitals as a preamble). The Data Protection Act 2018 is listed at section level plus "
        "numbered subsections (sec:N, sec:N(S)), schedules (sch:N) and numbered schedule paragraphs (sch:N(P)). "
        "Lettered points ((a), (b)) and sub-paragraphs are not listed: they are accepted when their parent is listed. "
        "This is the finest level at which a UK audit finding is usually cited (e.g. 'Article 32(1)', 'section 170(1)') "
        "and it is reliably numbered in the official XML. Provisions the source marks Repealed or Prospective (not yet "
        "in force) are excluded; paragraphs repealed inside a live provision carry no marker and are kept. "
        "Amending Annexes 1-2 of the UK GDPR are not listed. Identifiers the shared grammar cannot express "
        f"({', '.join(bad1 + bad2) or 'none'}) are omitted.",
        [gdpr, dpa_inst],
    )
    write_clause_file(
        "CCPA_CPRA",
        "section",
        "Listed at section level (sec:1798.100 ... sec:1798.199.100) of Civil Code Title 1.81.5. Section is what "
        "practitioners cite ('Cal. Civ. Code 1798.100'); lettered subdivisions are free-text inside each section "
        "(not separately numbered in the data), so they are accepted when the section is listed. The CPPA regulations "
        "(11 CCR 7000 et seq.) are out of scope for this file.",
        [ccpa()],
    )


if __name__ == "__main__":
    main()
