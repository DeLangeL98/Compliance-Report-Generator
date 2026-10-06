"""Extract valid clause identifiers for EU instruments from the Publications Office.

Sources are the official XHTML renderings served by the Publications Office
resource resolver (``https://publications.europa.eu/resource/celex/<CELEX>``).
Nothing is taken from memory or from a summarising model: every identifier is
parsed from the fetched markup and then cross-checked (see ``build_instrument``).

Produces GDPR.json, DORA.json, NIS2.json and MiFID_II.json (MiFID II + MiFIR).

Usage (repo root):  python3 -I tools/clause_sources/eu_oj.py [--cache DIR]
``--cache`` (default ``$CLAUDE_JOB_DIR/tmp/eu`` if set) stores raw downloads
OUTSIDE the repo; downloaded markup is treated purely as data.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

RETRIEVED_ON = "2026-10-06"
METHOD = "tools/clause_sources/eu_oj.py"
BASE = "https://publications.europa.eu/resource/celex/"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"

# EU legislation has articles such as 27da/27db (MiFIR); the shared grammar in
# common.py only allows one letter suffix, so widen it for this script.
common._IDENT = re.compile(common._IDENT.pattern.replace("art:\\d+[a-z]?", "art:\\d+[a-z]{0,3}"))

ART_RE = re.compile(r'<div class="eli-subdivision" id="art_(\d+[a-z]*)">')
BOUNDARY_RE = re.compile(r'<div class="eli-subdivision" id="(?:art|anx)_[^"]+">')
# original OJ markup: a numbered paragraph is a div id="NNN.PPP" whose first
# <p class="oj-normal"> starts with the marker; consolidated markup: span.no-parag (outside grid lists)
OJ_PARA_RE = re.compile(r'<div id="(\d{3})\.\d{3}">\s*<p class="oj-normal">\s*(\d+[a-z]*)\.\s')
# independent cross-check for original markup: any numbered oj-normal paragraph
OJ_PARA_ANY_RE = re.compile(r'<p class="oj-normal">\s*(\d+[a-z]*)\.\s')
RCT_RE = re.compile(r'<div[^>]*\bid="rct_(\d+)"')
ANX_RE = re.compile(r'<div[^>]*\bid="anx_([IVXLC]+)"')


class _ConsParas(HTMLParser):
    """Collect span.no-parag (outside grid lists) markers that are NOT inside a grid-list/grid-container.

    Amending articles quote paragraphs of other acts inside list containers; those
    must not be recorded as paragraphs of the amending article itself.
    """

    VOID = {"col", "br", "img", "hr", "meta", "link", "input"}

    def __init__(self):
        super().__init__()
        self.stack: list[bool] = []   # True for containers that mark quoted/list content
        self.nested = 0
        self.capture = False
        self.found: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        cls = dict(attrs).get("class") or ""
        is_list = tag == "div" and ("grid-container" in cls or "grid-list" in cls)
        self.stack.append(is_list)
        self.nested += is_list
        if tag == "span" and "no-parag" in cls.split() and not self.nested:
            self.capture = True

    def handle_endtag(self, tag):
        if tag in self.VOID or not self.stack:
            return
        self.nested -= self.stack.pop()
        self.capture = False

    def handle_data(self, data):
        if self.capture:
            m = re.fullmatch(r"\s*(\d+[a-z]*)\.\s*", data.replace("\xa0", " "))
            if m:
                self.found.append(m.group(1))
            self.capture = False


def consolidated_paragraphs(fragment: str) -> list[str]:
    parser = _ConsParas()
    parser.feed(fragment)
    return parser.found


class Doc:
    def __init__(self, celex: str, cache: Path):
        self.celex = celex
        self.url = BASE + celex
        f = cache / f"{celex}.xhtml"
        if not f.exists():
            cache.mkdir(parents=True, exist_ok=True)
            f.write_bytes(common.fetch(self.url, accept="application/xhtml+xml", lang="eng"))
        self.text = f.read_text(encoding="utf-8")
        self.consolidated = celex.startswith("0")

    def _slice(self, pos: int) -> str:
        m = BOUNDARY_RE.search(self.text, pos + 10)
        return self.text[pos: m.start() if m else len(self.text)]

    def articles(self) -> dict[str, list[str]]:
        """{article label: [numbered paragraph labels]} in document order."""
        out: dict[str, list[str]] = {}
        for m in ART_RE.finditer(self.text):
            label = m.group(1)
            if label in out:
                raise SystemExit(f"{self.celex}: duplicate article {label}")
            sl = self._slice(m.start())
            # the visible heading must agree with the div id
            h = re.search(r'class="(?:oj-ti-art|title-article-norm)"[^>]*>\s*Article\s+(\d+[a-z]*)\s*<', sl)
            if not h or h.group(1) != label:
                raise SystemExit(f"{self.celex}: heading/id mismatch for art_{label}: {h and h.group(1)}")
            if self.consolidated:
                paras = consolidated_paragraphs(sl)
            else:
                # only divs whose id prefix is THIS article: amending articles quote
                # paragraphs of other acts (e.g. id 026.003 inside DORA art 60)
                paras = [p for pre, p in OJ_PARA_RE.findall(sl) if int(pre) == int(re.match(r"\d+", label).group())]
                alt = OJ_PARA_ANY_RE.findall(sl)
                if alt != paras:
                    print(f"  note {self.celex} art {label}: div-based {paras} vs text-based {alt}",
                          file=sys.stderr)
            out[label] = paras
        return out

    def recitals(self) -> list[int]:
        return [int(x) for x in RCT_RE.findall(self.text)]

    def annexes(self) -> list[str]:
        return ANX_RE.findall(self.text)

    def article_text(self, label: str) -> str:
        sl = self._slice(self.text.index(f'id="art_{label}"'))
        return re.sub(r"<[^>]+>|\s+", " ", sl)


def split(label: str) -> tuple[int, str]:
    m = re.fullmatch(r"(\d+)([a-z]*)", label)
    return int(m.group(1)), m.group(2)


def check_paragraphs(celex: str, arts: dict[str, list[str]]) -> int:
    """Numbered paragraphs should run 1,2,3,... (letter-suffixed insertions allowed)."""
    n = 0
    for art, paras in arts.items():
        if len(set(paras)) != len(paras):
            raise SystemExit(f"{celex} art {art}: duplicate paragraph labels {paras}")
        if paras:
            base = sorted({int(re.match(r"\d+", p).group()) for p in paras})
            if base != list(range(1, max(base) + 1)):
                print(f"  WARNING {celex} art {art}: paragraph numbering not contiguous: {paras}",
                      file=sys.stderr)
        n += len(paras)
    return n


def build_instrument(code, title, version, doc: Doc, *, expected_last_article: int,
                     expected_recitals: int, expected_annexes: list[str],
                     recital_doc: Doc | None = None, repealed_ok: bool = False) -> dict:
    arts = doc.articles()
    nums = {split(a)[0] for a in arts}
    top = max(nums)
    last_label = max(arts, key=split)
    missing = sorted(set(range(1, expected_last_article + 1)) - nums)
    if top != expected_last_article:
        raise SystemExit(f"{code}: highest article {top} != expected {expected_last_article}")
    if missing and not repealed_ok:
        raise SystemExit(f"{code}: article numbers missing: {missing}")
    last_txt = doc.article_text(last_label)
    if "enter into force" not in last_txt and "addressed to" not in last_txt:
        raise SystemExit(f"{code}: last article {last_label} lacks entry-into-force/addressees wording")
    n_par = check_paragraphs(doc.celex, arts)

    ids: list[str] = []
    for a, paras in arts.items():
        ids.append(f"art:{a}")
        ids += [f"art:{a}({p})" for p in paras]

    rec = (recital_doc or doc).recitals()
    if sorted(rec) != list(range(1, len(rec) + 1)):
        raise SystemExit(f"{code}: recitals not contiguous/unique")
    if len(rec) != expected_recitals:
        raise SystemExit(f"{code}: {len(rec)} recitals != expected {expected_recitals}")
    ids += [f"recital:{r}" for r in rec]

    anx = doc.annexes()
    if anx != expected_annexes:
        raise SystemExit(f"{code}: annexes {anx} != expected {expected_annexes}")
    ids += [f"annex:{a}" for a in anx]

    if len(ids) != len(set(ids)):
        raise SystemExit(f"{code}: duplicate identifiers")
    print(f"{code}: {len(arts)} articles (missing numbers {missing or 'none'}), {n_par} paragraph ids, "
          f"{len(rec)} recitals, {len(anx)} annexes {anx}; last article {last_label}", file=sys.stderr)
    source = doc.url if not recital_doc else f"{doc.url} (articles, annexes); {recital_doc.url} (recitals)"
    return {"code": code, "title": title, "version": version, "source": source,
            "retrieved_on": RETRIEVED_ON, "retrieval_method": METHOD, "identifiers": ids}


def latest_consolidation(prefix: str) -> str:
    """Latest consolidated CELEX '<prefix>-YYYYMMDD' per the Publications Office SPARQL endpoint."""
    q = ('PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> '
         'SELECT ?c WHERE { ?w cdm:resource_legal_id_celex ?c . '
         f'FILTER(STRSTARTS(STR(?c),"{prefix}-")) }}')
    body = common.fetch(SPARQL + "?" + urllib.parse.urlencode({"query": q}), accept="text/csv").decode()
    found = sorted(set(re.findall(rf'"({prefix}-\d{{8}})"', body)))
    if not found:
        raise SystemExit(f"no consolidated versions found for {prefix}")
    return found[-1]


RATIONALE = (
    "Articles and numbered paragraphs are the units an auditor tests a control against "
    "(e.g. GDPR art:32(1)); lettered points and sub-points are NOT listed, but references to "
    "them are accepted when their parent identifier is listed. A paragraph identifier is only "
    "listed where the paragraph carries an explicit number in the official text (single-paragraph "
    "articles get no paragraph identifier). Recitals are listed as recital:N because the "
    "purpose of the legislation is expressed there and regulators and courts cite them"
    "{annex}."
)


def main() -> None:
    cj = os.environ.get("CLAUDE_JOB_DIR")
    cache = Path(sys.argv[sys.argv.index("--cache") + 1]) if "--cache" in sys.argv else (
        Path(cj) / "tmp" / "eu" if cj else Path("clause_cache_eu"))
    if str(cache.resolve()).startswith(str(common.REPO_ROOT)):
        raise SystemExit("cache directory must be outside the repository")

    gdpr = Doc("32016R0679", cache)
    common.write_clause_file("GDPR", "article-paragraph", RATIONALE.format(annex=" (the GDPR has no annexes)"), [
        build_instrument("GDPR", "Regulation (EU) 2016/679 (General Data Protection Regulation)",
                         "OJ L 119, 4.5.2016, original OJ text (CELEX 32016R0679)",
                         gdpr, expected_last_article=99, expected_recitals=173, expected_annexes=[])])

    dora = Doc("32022R2554", cache)
    common.write_clause_file("DORA", "article-paragraph", RATIONALE.format(annex=" (DORA has no annexes)"), [
        build_instrument("DORA", "Regulation (EU) 2022/2554 (Digital Operational Resilience Act)",
                         "OJ L 333, 27.12.2022, original OJ text (CELEX 32022R2554)",
                         dora, expected_last_article=64, expected_recitals=106, expected_annexes=[])])

    nis2 = Doc("32022L2555", cache)
    inst = build_instrument("NIS2", "Directive (EU) 2022/2555 (NIS 2 Directive)",
                            "OJ L 333, 27.12.2022, original OJ text (CELEX 32022L2555)",
                            nis2, expected_last_article=46, expected_recitals=144,
                            expected_annexes=["I", "II", "III"])
    # Annex III is the correlation table to the repealed NIS1 Directive, not a requirement.
    inst["identifiers"].remove("annex:III")
    common.write_clause_file("NIS2", "article-paragraph", RATIONALE.format(
        annex="; annex:I (sectors of high criticality) and annex:II (other critical sectors) are listed "
              "because entity scope is determined by them. Annex III is only the correlation table to "
              "the repealed Directive (EU) 2016/1148 and is not listed"), [inst])

    # MiFID II / MiFIR: consolidated article text; recitals from the original OJ text
    # (the consolidated renderings do not carry recitals).
    c_dir = latest_consolidation("02014L0065")
    c_reg = latest_consolidation("02014R0600")
    d_orig, d_cons = Doc("32014L0065", cache), Doc(c_dir, cache)
    r_orig, r_cons = Doc("32014R0600", cache), Doc(c_reg, cache)

    def fmt(c: str) -> str:
        return f"{c[-8:-4]}-{c[-4:-2]}-{c[-2:]}"

    for orig, cons in ((d_orig, d_cons), (r_orig, r_cons)):
        oa, ca = orig.articles(), cons.articles()
        print(f"  {cons.celex} vs original: articles only in original {sorted(set(oa) - set(ca), key=split)}, "
              f"only in consolidated {sorted(set(ca) - set(oa), key=split)}", file=sys.stderr)
        for a in sorted(set(oa) & set(ca), key=split):
            if oa[a] != ca[a]:
                print(f"    art {a}: original paras {oa[a]} consolidated {ca[a]}", file=sys.stderr)

    mifid = build_instrument(
        "MiFID_II", "Directive 2014/65/EU (MiFID II)",
        f"Consolidated version of {fmt(c_dir)} (CELEX {c_dir}) for articles and annexes; recitals from the "
        "original OJ L 173, 12.6.2014 text (CELEX 32014L0065). Articles repealed by later amendments "
        "are absent from the consolidated text and therefore not listed.",
        d_cons, expected_last_article=97, recital_doc=d_orig, expected_recitals=170,
        expected_annexes=["I", "II", "III", "IV"], repealed_ok=True)
    mifir = build_instrument(
        "MiFIR", "Regulation (EU) No 600/2014 (MiFIR)",
        f"Consolidated version of {fmt(c_reg)} (CELEX {c_reg}) for articles; recitals from the "
        "original OJ L 173, 12.6.2014 text (CELEX 32014R0600). Articles repealed by later amendments "
        "are absent from the consolidated text and therefore not listed.",
        r_cons, expected_last_article=55, recital_doc=r_orig, expected_recitals=55,
        expected_annexes=[], repealed_ok=True)
    common.write_clause_file("MiFID_II", "article-paragraph", RATIONALE.format(
        annex="; annexes of Directive 2014/65/EU are listed as annex:I to annex:IV. MiFID II is a Directive and "
              "MiFIR a Regulation; both instruments are in this file because auditors test against the "
              "two together. Consolidated texts are used so inserted articles such as 16a or 27da "
              "are valid references"), [mifid, mifir])


if __name__ == "__main__":
    main()
