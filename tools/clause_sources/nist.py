"""Extract valid clause identifiers for NIST CSF 2.0 and NIST SP 800-53 Rev. 5.

Run from the repository root::

    python3 -I tools/clause_sources/nist.py

Writes saaf/knowledge/clause_data/NIST_CSF.json and NIST_800_53.json.

Sources (both fetched and parsed in code; nothing is typed in by hand):

* CSF 2.0: the official NIST CSF 2.0 Reference Tool (CPRT) XLSX export served by
  NIST CSRC. The workbook is read with zipfile + ElementTree (stdlib). The
  export itself carries no version string beyond "CSF 2.0" / "Final"; the
  publication metadata (NIST CSWP 29) is cross-checked against the PDF.
* SP 800-53 Rev. 5: the official NIST OSCAL catalog JSON published in
  usnistgov/oscal-content, pinned to a commit so the run is reproducible.

Sanity checks abort the run (non-zero exit) on any mismatch.
"""

from __future__ import annotations

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fetch, write_clause_file  # noqa: E402

RETRIEVED_ON = "2026-10-06"
METHOD = "tools/clause_sources/nist.py"

CSF_XLSX_URL = "https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all"
CSF_PDF_URL = "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"

# Commit of usnistgov/oscal-content that last touched the catalog (the file as
# published on 2026-05-13). Pinned so the data can be regenerated exactly.
OSCAL_COMMIT = "78650f02ad9321bb7b817846f8fbd4f2bcd620de"
OSCAL_URL = (
    "https://raw." + "githubusercontent.com/usnistgov/oscal-content/"
    f"{OSCAL_COMMIT}/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"SANITY CHECK FAILED: {msg}")
    print(f"ok: {msg}", file=sys.stderr)


# --------------------------------------------------------------------- CSF 2.0

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _read_sheet(xlsx: bytes, sheet_name: str) -> list[dict[str, str]]:
    """Return rows of the named worksheet as {column letter: text}."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    shared = [
        "".join(t.text or "" for t in si.iter(_M + "t"))
        for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
    ]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    rid = next(s.get(rid_ns) for s in wb.iter(_M + "sheet") if s.get("name") == sheet_name)
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    rows = []
    for row in ET.fromstring(z.read(path)).iter(_M + "row"):
        cells = {}
        for c in row:
            v = c.find(_M + "v")
            if v is None or v.text is None:
                continue
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            cells[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        rows.append(cells)
    return rows


def _pdf_text(pdf: bytes) -> str:
    """Crude text extraction: concatenate the literal strings of TJ/Tj operators."""
    out: list[str] = []
    for m in re.finditer(rb"stream\r?\n", pdf):
        end = pdf.find(b"endstream", m.end())
        try:
            data = zlib.decompress(pdf[m.end():end])
        except zlib.error:
            continue
        for arr in re.finditer(rb"\[((?:[^\]\\]|\\.)*)\]\s*TJ|\(((?:[^()\\]|\\.)*)\)\s*Tj", data):
            body = arr.group(1) if arr.group(1) is not None else b"(" + arr.group(2) + b")"
            parts = re.findall(rb"\(((?:[^()\\]|\\.)*)\)", body)
            s = b"".join(parts)
            s = re.sub(rb"\\([()\\])", rb"\1", s)
            out.append(s.decode("latin-1"))
        out.append("\n")
    return "".join(out)


def build_csf() -> None:
    rows = _read_sheet(fetch(CSF_XLSX_URL), "CSF 2.0")
    fns: list[str] = []
    cats: list[str] = []
    subs: list[str] = []
    # The export also lists the CSF 1.1 categories/subcategories that 2.0 withdrew,
    # marked "[Withdrawn: Incorporated into ...]". These are NOT valid in 2.0 and are
    # skipped (together with anything under a withdrawn category).
    withdrawn_cats: list[str] = []
    withdrawn_subs: list[str] = []
    cat_withdrawn = False
    for r in rows:
        if "A" in r and (m := re.match(r"^[A-Z]+ \(([A-Z]{2})\):", r["A"])):
            fns.append(m.group(1))
        elif "B" in r and (m := re.match(r"^.+ \(([A-Z]{2}\.[A-Z]{2})\):", r["B"])):
            cat_withdrawn = "[Withdrawn" in r["B"]
            (withdrawn_cats if cat_withdrawn else cats).append(m.group(1))
        elif "C" in r and (m := re.match(r"^([A-Z]{2}\.[A-Z]{2}-\d+):", r["C"])):
            if cat_withdrawn or "[Withdrawn" in r["C"]:
                withdrawn_subs.append(m.group(1))
            else:
                subs.append(m.group(1))

    print(f"CSF parsed: {len(fns)} functions, {len(cats)} categories, {len(subs)} subcategories "
          f"(skipped withdrawn CSF 1.1 rows: {len(withdrawn_cats)} categories, "
          f"{len(withdrawn_subs)} subcategories)", file=sys.stderr)
    check(not set(withdrawn_cats) & set(cats) and not set(withdrawn_subs) & set(subs),
          "CSF: no identifier is both active and withdrawn")
    check(len(set(fns)) == len(fns) and len(set(cats)) == len(cats) and len(set(subs)) == len(subs),
          "CSF: no duplicate identifiers")
    check(all(c[:2] in fns for c in cats) and all(s[:5] in cats for s in subs),
          "CSF: every category/subcategory sits under a listed function/category")
    check(not any(re.match(r"^[A-Z]{2}\.[A-Z]{2}-\d$", s) for s in subs),
          "CSF: no v1.1-style identifiers (e.g. PR.AC-1) in the data")

    # Cross-check against the publication (NIST CSWP 29) text.
    text = _pdf_text(fetch(CSF_PDF_URL, timeout=180))
    flat = re.sub(r"\s+", " ", text)
    check("Cybersecurity Framework (CSF) 2.0" in flat, "CSWP 29 PDF is the CSF 2.0 publication")
    check("CSWP 29" in flat, "PDF identifies itself as NIST CSWP 29")
    check(bool(re.search(r"February 26, 2024", flat)), "PDF carries the February 26, 2024 publication date")
    pdf_subs = set(re.findall(r"\b([A-Z]{2}\.[A-Z]{2}-\d{2})\b", flat))
    pdf_cats = set(re.findall(r"\b([A-Z]{2}\.[A-Z]{2})\b(?!-)", flat))
    print(f"CSWP 29 PDF text mentions {len(pdf_subs)} subcategory ids", file=sys.stderr)
    check(pdf_subs == set(subs), "CSF: subcategory ids in the CSWP 29 PDF equal the CPRT export")
    check(set(cats) <= pdf_cats, "CSF: every category appears in the CSWP 29 PDF")
    # The CSF 2.0 Core has 6 functions, 22 categories and 106 subcategories.
    check(len(fns) == 6 and len(cats) == 22 and len(subs) == 106,
          "CSF: 6 functions / 22 categories / 106 subcategories (the counts of the CSF 2.0 Core)")

    identifiers = ([f"fn:{f}" for f in fns] + [f"cat:{c}" for c in cats]
                   + [f"sub:{s}" for s in subs])
    write_clause_file(
        "NIST_CSF",
        "subcategory",
        "The CSF 2.0 subcategory is the testable outcome statement of the Core and what a "
        "profile or assessment is scored against; functions and categories are listed so "
        "coarser references are also accepted. Implementation Examples and Informative "
        "References in the Core are non-normative illustrations and are deliberately "
        "excluded. CSF 1.1 identifiers (e.g. PR.AC-1) are not valid in 2.0 and are not "
        "listed.",
        [{
            "code": "CSF_2_0",
            "title": "NIST Cybersecurity Framework (CSF) 2.0 Core",
            "version": "CSF 2.0 (NIST CSWP 29, February 26, 2024); CSF 2.0 Reference Tool "
                       "(CPRT) export, change log 'Final'",
            "source": CSF_XLSX_URL,
            "retrieved_on": RETRIEVED_ON,
            "retrieval_method": METHOD,
            "identifiers": identifiers,
        }],
    )


# ------------------------------------------------------------------ SP 800-53

def _walk(controls: list[dict]):
    for c in controls:
        yield c
        yield from _walk(c.get("controls", []))


def _label(ctrl: dict) -> str:
    """The unpadded publication label: prop name=label with no class."""
    vals = [p["value"] for p in ctrl.get("props", [])
            if p["name"] == "label" and "class" not in p]
    if len(vals) != 1:
        raise SystemExit(f"{ctrl['id']}: expected exactly one unpadded label prop")
    return vals[0]


def _padded(ctrl: dict) -> str:
    vals = [p["value"] for p in ctrl.get("props", [])
            if p["name"] == "label" and p.get("class") == "zero-padded"]
    return vals[0] if vals else ""


def build_800_53() -> None:
    doc = json.loads(fetch(OSCAL_URL, timeout=180))
    cat = doc["catalog"]
    meta = cat["metadata"]
    version, modified, oscal_v = meta["version"], meta["last-modified"], meta["oscal-version"]
    print(f"catalog: {meta['title']!r} version={version} last-modified={modified} "
          f"oscal-version={oscal_v}", file=sys.stderr)
    check(" Rev 5" in meta["title"] and version.startswith("5."),
          "catalog metadata identifies SP 800-53 Revision 5 (5.x)")

    groups = cat["groups"]
    check(all(g.get("class") == "family" for g in groups), "all top-level groups are families")
    check(len(groups) == 20, "20 control families")

    kept: list[str] = []
    n_base = n_enh = w_base = w_enh = 0
    for g in groups:
        fam = g["props"][0]["value"]
        for c in _walk(g["controls"]):
            label = _label(c)
            # Canonical (unpadded) label must be the OSCAL id upper-cased with ".n" -> "(n)".
            oscal_form = re.sub(r"\.(\d+)$", r"(\1)", c["id"].upper())
            if label != oscal_form:
                raise SystemExit(f"label {label} does not match OSCAL id {c['id']}")
            padded = _padded(c)
            unpadded = re.sub(r"(?<=[-(])0+(?=\d)", "", padded)
            if unpadded != label:
                raise SystemExit(f"padded label {padded} does not reduce to {label}")
            if not label.startswith(fam + "-"):
                raise SystemExit(f"{label} outside family {fam}")
            is_enh = "(" in label
            if is_enh != (c.get("class") == "SP800-53-enhancement"):
                raise SystemExit(f"{label}: class {c.get('class')} disagrees with label form")
            withdrawn = any(p["name"] == "status" and p["value"] == "withdrawn"
                            for p in c.get("props", []))
            if withdrawn:
                w_enh += is_enh
                w_base += not is_enh
                continue
            n_enh += is_enh
            n_base += not is_enh
            kept.append(label)

    total = n_base + n_enh + w_base + w_enh
    print(f"SP 800-53: {total} catalog entries = {n_base} controls + {n_enh} enhancements "
          f"active; withdrawn excluded: {w_base} controls + {w_enh} enhancements",
          file=sys.stderr)
    check(len(set(kept)) == len(kept), "800-53: no duplicate identifiers")
    kset = set(kept)
    check(all(re.sub(r"\(\d+\)$", "", k) in kset for k in kept),
          "800-53: every kept enhancement's parent control is also kept")
    check(all(re.fullmatch(r"[A-Z]{2}-\d+(\(\d+\))?", k) for k in kept),
          "800-53: all labels are in unpadded canonical form")
    check("AC-2" in kset and "AC-2(1)" in kset and "SI-2" in kset
          and "AC-02" not in kset and "AC-13" not in kset,
          "800-53: spot IDs (AC-2, AC-2(1), SI-2 present; AC-02 padded and withdrawn AC-13 absent)")
    # The catalog metadata carries no stated control counts; the 20-family check above and
    # the structural checks are what can be verified from the source itself.

    write_clause_file(
        "NIST_800_53",
        "control-enhancement",
        "Auditors test and assess individual controls and control enhancements (SP 800-53A "
        "assessment objectives attach at that level), so both ctrl:XX-n and ctrl:XX-n(m) are "
        "listed; finer-grained references (e.g. parts a/b of a control statement or "
        "assessment objectives) are accepted when the parent identifier is listed. "
        "Identifiers use the unpadded publication form (AC-2, AC-2(1)), taken from the "
        "catalog's unpadded 'label' property. Controls and enhancements the catalog marks "
        "with status=withdrawn are excluded because they are not valid requirements in the "
        "current Rev. 5 baseline.",
        [{
            "code": "SP800_53_R5",
            "title": "NIST SP 800-53 Rev. 5, Security and Privacy Controls for Information "
                     "Systems and Organizations (OSCAL catalog)",
            "version": f"Rev. 5, OSCAL catalog version {version} (last-modified {modified}, "
                       f"OSCAL {oscal_v}); usnistgov/oscal-content commit {OSCAL_COMMIT}",
            "source": OSCAL_URL,
            "retrieved_on": RETRIEVED_ON,
            "retrieval_method": METHOD,
            "identifiers": [f"ctrl:{k}" for k in kept],
        }],
    )


if __name__ == "__main__":
    build_csf()
    build_800_53()
