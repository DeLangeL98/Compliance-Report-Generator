"""Print the provenance table for a clause-list PR from the committed data files.

Usage (from the repository root): ``python3 -I tools/clause_sources/provenance_table.py``

One row per instrument. ``last_reviewed`` is the date the agent retrieved the
source; it is NOT a maintainer's verification (see #9) until a maintainer has
checked the source and confirmed the row.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "saaf" / "knowledge" / "clause_data"


def main() -> int:
    rows = []
    for path in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for inst in data["instruments"]:
            rows.append((
                data["framework_key"], inst["code"], inst["title"], data["granularity"],
                len(inst["identifiers"]), inst["version"], inst["source"], inst["retrieved_on"],
            ))
    print("| framework | instrument | granularity | identifiers | version | source | last_reviewed |")
    print("|---|---|---|---:|---|---|---|")
    for key, code, _title, gran, n, version, source, retrieved in rows:
        print(f"| {key} | {code} | {gran} | {n} | {version} | {source} | {retrieved} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
