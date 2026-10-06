"""End-to-end tests for the clause lists against the LATEST official sources (issue #7).

The unit tests run on the committed snapshot and never touch the network.
These tests re-run every extraction script in ``tools/clause_sources/`` against
the live official source, writing to a temporary directory (the committed files
are never modified), and then check two things:

1. **Functional**: the clause checks (``check_references``) give the expected
   outcome for known-good and known-bad references when run on the *freshly
   extracted* lists (``tests.test_clauses.REAL_EXPECTATIONS``).
2. **Drift**: the committed identifier sets still equal the freshly extracted
   ones. A failure lists the added / removed identifiers and means the
   committed list is stale; regenerate it in a pull request that cites the
   sources.

They need network access and take several minutes (the CCPA source is a
~1.2 GB zip read through HTTP range requests), so they only run when
``SAAF_E2E=1`` is set. CI runs them as the separate "Clause sources e2e" job
(.github/workflows/e2e-clauses.yml), not in the normal test job.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from saaf.core.reference_check import check_references  # noqa: E402
from saaf.knowledge.clauses import CLAUSE_DATA_DIR, load_clause_lists  # noqa: E402
from test_clauses import FULL_NAMES, REAL_EXPECTATIONS  # noqa: E402

# script -> framework keys it writes
SCRIPTS = {
    "eu_oj.py": ["GDPR", "DORA", "NIS2", "MiFID_II"],
    "uk_ca_law.py": ["UK_GDPR", "CCPA_CPRA"],
    "us_law.py": ["HIPAA", "GLBA"],
    "nist.py": ["NIST_CSF", "NIST_800_53"],
}
# optional: SAAF_E2E_SCRIPTS=nist.py,eu_oj.py limits the run (local use)
_ONLY = {s for s in os.environ.get("SAAF_E2E_SCRIPTS", "").split(",") if s}

_TMP = None
FRESH: dict = {}


def setUpModule():
    global _TMP
    if os.environ.get("SAAF_E2E") != "1":
        raise unittest.SkipTest("set SAAF_E2E=1 to run the live-source e2e tests")
    _TMP = tempfile.TemporaryDirectory(prefix="saaf-e2e-")
    out, cache = Path(_TMP.name, "out"), Path(_TMP.name, "cache")
    cache.mkdir()
    env = {**os.environ, "SAAF_CLAUSE_OUT_DIR": str(out)}
    for script in SCRIPTS:
        if _ONLY and script not in _ONLY:
            continue
        cmd = [sys.executable, "-I", str(PROJECT_ROOT / "tools" / "clause_sources" / script)]
        if script in ("eu_oj.py", "us_law.py"):
            cmd += ["--cache", str(cache / script)]
        done = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"{script} failed ({done.returncode}):\n{done.stderr[-3000:]}")
    FRESH.update(load_clause_lists(out))


def tearDownModule():
    if _TMP is not None:
        _TMP.cleanup()


class TestFreshSources(unittest.TestCase):
    def test_all_expected_frameworks_were_extracted(self):
        want = {k for s, ks in SCRIPTS.items() if not _ONLY or s in _ONLY for k in ks}
        self.assertEqual(want - set(FRESH), set())

    def test_checks_on_freshly_extracted_lists(self):
        for key, ref, expected in REAL_EXPECTATIONS:
            if key not in FRESH:
                continue
            with self.subTest(ref=ref):
                mapping = NS(framework_matches=[
                    NS(key=k, full_name=FULL_NAMES.get(k, k)) for k in FRESH])
                report = NS(
                    framework_assessments=[NS(framework_name="x", control_objectives=[
                        NS(control_id="C-1", requirement_source=ref)])],
                    mandatory_regulations=[],
                )
                result = check_references(report, mapping, FRESH)[0]
                self.assertEqual(result.check, expected,
                                 f"{ref!r}: the latest official source gives {result.check}")
                self.assertEqual(result.status, "unverified")


class TestCommittedListsAreCurrent(unittest.TestCase):
    def test_identifiers_match_latest_sources(self):
        committed = load_clause_lists(CLAUSE_DATA_DIR)
        for key, fresh in FRESH.items():
            old = {i.code: i for i in committed[key].instruments}
            for inst in fresh.instruments:
                with self.subTest(framework=key, instrument=inst.code):
                    self.assertIn(inst.code, old)
                    added = sorted(inst.identifiers - old[inst.code].identifiers)
                    removed = sorted(old[inst.code].identifiers - inst.identifiers)
                    self.assertFalse(
                        added or removed,
                        f"{inst.code} drifted from {inst.source}: "
                        f"{len(added)} new (e.g. {added[:5]}), {len(removed)} gone (e.g. {removed[:5]}). "
                        "Regenerate with tools/clause_sources/ and cite the new source versions.")


if __name__ == "__main__":
    unittest.main()
