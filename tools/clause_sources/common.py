"""Shared helpers for the clause-list extraction scripts.

Each script in this package fetches an OFFICIAL source, parses it
deterministically (no summarising model, no memory) and writes one
``saaf/knowledge/clause_data/<FRAMEWORK_KEY>.json`` file through
:func:`write_clause_file`, which enforces the data format below.

Run a script from the repository root, e.g.
``python -I tools/clause_sources/eu_oj.py``. Regenerating the data is done
through a pull request that cites the sources (see issue #7).

Data format (one JSON file per registry framework key)::

    {
      "framework_key": "GDPR",
      "granularity": "article-paragraph",       # short label, see GRANULARITIES
      "granularity_rationale": "why this level is what an auditor tests against",
      "instruments": [
        {
          "code": "GDPR",                       # unique within the file
          "title": "Regulation (EU) 2016/679 (GDPR)",
          "version": "OJ L 119, 4.5.2016",      # edition / consolidation date
          "source": "https://...",              # the official URL actually fetched
          "retrieved_on": "2026-10-06",         # ISO date of retrieval
          "retrieval_method": "tools/clause_sources/eu_oj.py",
          "identifiers": ["art:1", "art:32", "art:32(1)", "recital:1", ...]
        }
      ]
    }

Identifier grammar (lower case, no spaces; paragraph numbers/letters exactly as
numbered in the source; points such as (a)/(b) are only listed where the
granularity says so):

    art:<n>[<letters>][(<para>)...]   article, e.g. art:32, art:32(1), art:45a, art:27da
    recital:<n>                      recital, e.g. recital:83
    annex:<ROMAN-or-letter>          annex, e.g. annex:I
    sec:<n>[.<n>][<letter>][(<sub>)...]  section of an Act/Code, e.g. sec:170, sec:1798.100(a)
    sch:<n>[(<para>)...]             schedule, e.g. sch:2, sch:2(1)
    cfr:<part>.<section>[(<p>)...]   US CFR, e.g. cfr:164.312, cfr:164.312(a)(2)(iv)
    ctrl:<FAMILY>-<n>[(<enh>)]       NIST SP 800-53 control, e.g. ctrl:AC-2, ctrl:AC-2(1)
    fn:<XX> | cat:<XX.YY> | sub:<XX.YY-NN>   NIST CSF 2.0 function/category/subcategory
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "saaf" / "knowledge" / "clause_data"
USER_AGENT = "Mozilla/5.0 (compatible; SAAF-clause-index-builder/1.0)"

# Label for the level that is validated. Whatever the label, references MORE
# specific than the listed identifiers are accepted when their parent
# identifier is listed (decision on issue #7).
GRANULARITIES = {
    "article-paragraph",
    "section-paragraph",
    "section",
    "cfr-paragraph",
    "control-enhancement",
    "subcategory",
}

_IDENT = re.compile(
    r"^(?:"
    r"art:\d+[a-z]{0,3}(?:\(\w+\))*"
    r"|recital:\d+"
    r"|annex:(?:[IVXLC]+|[A-Z])"
    r"|sec:\d+(?:\.\d+)*[a-z]{0,3}(?:\(\w+\))*"
    r"|sch:\d+[a-z]{0,3}(?:\(\w+\))*"
    r"|cfr:\d+\.\d+(?:\(\w+\))*"
    r"|ctrl:[A-Z]{2}-\d+(?:\(\d+\))?"
    r"|fn:[A-Z]{2}"
    r"|cat:[A-Z]{2}\.[A-Z]{2}"
    r"|sub:[A-Z]{2}\.[A-Z]{2}-\d{2}"
    r")$"
)


def fetch(url: str, *, accept: str | None = None, lang: str | None = None,
          retries: int = 3, timeout: int = 90) -> bytes:
    """GET a URL with a UA header and simple retry; returns the raw body."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if lang:
        headers["Accept-Language"] = lang
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - report after retries
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def natural_key(identifier: str) -> list:
    """Sort key that orders art:2 before art:10 and art:2 before art:2(1)."""
    # (0, n) for numbers, (1, s) for text: a total order even when labels such
    # as sec:3(a1) and sec:3(1) put a number and text in the same position.
    return [(0, int(t), "") if t.isdigit() else (1, 0, t)
            for t in re.findall(r"\d+|[A-Za-z]+|\W", identifier)]


def write_clause_file(framework_key: str, granularity: str, rationale: str,
                      instruments: list[dict]) -> Path:
    """Validate and write ``clause_data/<framework_key>.json`` (sorted, stable)."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"unknown granularity {granularity!r}")
    if not rationale.strip():
        raise ValueError("granularity_rationale is required")
    codes: set[str] = set()
    for inst in instruments:
        for field in ("code", "title", "version", "source", "retrieved_on",
                      "retrieval_method", "identifiers"):
            if not inst.get(field):
                raise ValueError(f"{framework_key}: instrument missing {field!r}")
        if inst["code"] in codes:
            raise ValueError(f"{framework_key}: duplicate instrument code {inst['code']}")
        codes.add(inst["code"])
        date.fromisoformat(inst["retrieved_on"])
        ids = set(inst["identifiers"])
        bad = sorted(i for i in ids if not _IDENT.match(i))
        if bad:
            raise ValueError(f"{framework_key}/{inst['code']}: malformed identifiers {bad[:10]}")
        inst["identifiers"] = sorted(ids, key=natural_key)
    out = {
        "framework_key": framework_key,
        "granularity": granularity,
        "granularity_rationale": rationale.strip(),
        "instruments": instruments,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{framework_key}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {i["code"]: len(i["identifiers"]) for i in instruments}
    print(f"wrote {path.relative_to(REPO_ROOT)}  {counts}", file=sys.stderr)
    return path


def contiguous(numbers: Iterable[int], expected_last: int) -> bool:
    """True if 1..expected_last are all present (sanity check on article counts)."""
    return set(range(1, expected_last + 1)) <= set(numbers)
