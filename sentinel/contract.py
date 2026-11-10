"""Hostile-model contract checks (CT0xx).

The idea: treat the LLM as an untrusted party and replay crafted responses
through the repository's real parse and render code. A small adapter module in
the repository tells Sentinel how to call that code.

Adapter API (a plain Python file; see examples/):

Required
    trusted_input() -> object
        The engagement input the agent was really given.
    model_output() -> dict
        A valid model response (as the JSON object the model would return).
    parse(raw: str, trusted_input) -> report
        The repo's real parse/validate path. Must raise when it rejects input.

Optional
    AGENT_OWNED: dict[str, object | None]
        Dotted paths the agent must own, mapped to a hostile value the model
        might send (None = Sentinel picks one for strings).            -> CT001
    render(report) -> str
        Render the report to text (use a wide console, e.g. width=1000). -> CT002
    mapping_cases() -> iterable of dict(id, mandatory, selected, problems=[])
        Every input combination with the mandatory keys the rules require and
        the keys the mapper actually selected; ``problems`` lists any
        invariant violations the adapter detects for that case.           -> CT003
    EMPTY_OK: bool
        Set True if an empty report is a legitimate outcome (skips CT004).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import logging
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, List, Tuple

from sentinel.report import Finding

DEFAULT_HOSTILE_STR = "../../SENTINEL-HOSTILE"
CRASH_PAYLOAD = "[/sentinel]"
CANARY = "S1[a]C2"   # an unknown-style tag: a markup-parsing renderer silently drops "[a]"
LINK_PAYLOAD = "[link=https://sentinel.invalid]x[/link]"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_adapter(path: Path, repo_root: Path) -> ModuleType:
    root = str(repo_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("sentinel_adapter", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("trusted_input", "model_output", "parse"):
        if not callable(getattr(mod, name, None)):
            raise AttributeError(f"adapter {path} must define {name}()")
    return mod


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(value)
    return value


def _get(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = getattr(cur, part)
    return cur


def _set(data: Any, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur[int(part)] if isinstance(cur, list) else cur.setdefault(part, {})
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _string_leaves(data: Any, prefix: str = "") -> Iterator[Tuple[str, str]]:
    if isinstance(data, dict):
        for k, v in data.items():
            yield from _string_leaves(v, f"{prefix}{k}.")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _string_leaves(v, f"{prefix}{i}.")
    elif isinstance(data, str):
        yield prefix[:-1], data


def _empty_lists(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: ([] if isinstance(v, list) else _empty_lists(v)) for k, v in data.items()}
    return data


def _try_parse(adapter: ModuleType, data: dict, inp: Any) -> Tuple[Any, str]:
    try:
        return adapter.parse(json.dumps(data), inp), ""
    except Exception as e:  # rejection is a legitimate outcome
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# CT001 agent-owned fields
# ---------------------------------------------------------------------------

def check_agent_owned(adapter: ModuleType) -> List[Finding]:
    owned = getattr(adapter, "AGENT_OWNED", None) or {}
    if not owned:
        return [Finding("CT001", "info", "Adapter declares no AGENT_OWNED fields; CT001 skipped.")]
    inp = adapter.trusted_input()
    base = adapter.model_output()
    leaked, unparseable = [], []
    for path, hostile in owned.items():
        if hostile is None:
            hostile = DEFAULT_HOSTILE_STR
        data = copy.deepcopy(base)
        _set(data, path, hostile)
        report, err = _try_parse(adapter, data, inp)
        if report is None:
            unparseable.append(f"{path}: rejected ({err[:120]})")
            continue
        try:
            actual = _plain(_get(report, path))
        except (AttributeError, KeyError, IndexError, TypeError):
            continue
        if actual == _plain(hostile):
            leaked.append(f"{path} = {json.dumps(_plain(hostile))[:80]}")
    out = []
    if leaked:
        out.append(Finding(
            "CT001", "error",
            f"{len(leaked)} agent-owned field(s) keep the value the model sent.",
            details=leaked,
            hint="after validation, overwrite these fields from trusted state (input, uuid4(), "
                 "clock) and remove them from the schema shown to the model"))
    if not leaked:
        out.append(Finding(
            "CT001", "info",
            f"All {len(owned)} agent-owned field(s) ignore model-supplied values "
            f"({len(owned) - len(unparseable)} overwritten, {len(unparseable)} rejected).",
            details=unparseable))
    return out


# ---------------------------------------------------------------------------
# CT002 render injection
# ---------------------------------------------------------------------------

def check_render_injection(adapter: ModuleType) -> List[Finding]:
    render = getattr(adapter, "render", None)
    if not callable(render):
        return [Finding("CT002", "info", "Adapter defines no render(); CT002 skipped.")]
    owned = set((getattr(adapter, "AGENT_OWNED", None) or {}).keys())
    inp = adapter.trusted_input()
    base = adapter.model_output()
    crashes, mangled, tested = [], [], 0
    for path, original in _string_leaves(base):
        if any(path == o or path.startswith(o + ".") for o in owned):
            continue
        data = copy.deepcopy(base)
        _set(data, path, f"{original} {CANARY} {CRASH_PAYLOAD} {LINK_PAYLOAD}")
        report, _ = _try_parse(adapter, data, inp)
        if report is None:
            continue  # field is constrained (enum etc.); the model cannot inject here
        tested += 1
        try:
            text = render(report)
        except Exception as e:
            crashes.append(f"{path}: {type(e).__name__}: {str(e).splitlines()[0][:100]}")
            continue
        if CANARY not in (text or ""):
            mangled.append(path)
    out = []
    if crashes:
        out.append(Finding(
            "CT002", "error",
            f"Renderer raised on model text in {len(crashes)} of {tested} free-text fields "
            f"(payload {CRASH_PAYLOAD!r}). A paid, valid run ends in a crash.",
            details=crashes,
            hint="escape model text before it reaches a markup-aware renderer "
                 "(rich.markup.escape / Text(...) / markup=False)"))
    if mangled:
        out.append(Finding(
            "CT002", "error",
            f"Renderer silently altered model text in {len(mangled)} field(s): "
            f"{CANARY!r} did not survive, so '[...]' content is interpreted as markup "
            "(links can be injected the same way).",
            details=mangled,
            hint="escape model text before rendering"))
    if not out:
        out.append(Finding("CT002", "info", f"Renderer safe on {tested} free-text fields."))
    return out


# ---------------------------------------------------------------------------
# CT003 mapping completeness
# ---------------------------------------------------------------------------

def check_mapping(adapter: ModuleType) -> List[Finding]:
    cases_fn = getattr(adapter, "mapping_cases", None)
    if not callable(cases_fn):
        return [Finding("CT003", "info", "Adapter defines no mapping_cases(); CT003 skipped.")]
    total, bad = 0, []
    for case in cases_fn():
        total += 1
        missing = sorted(set(case.get("mandatory", ())) - set(case.get("selected", ())))
        problems = list(case.get("problems", ()))
        if missing:
            problems.insert(0, "drops mandatory " + ", ".join(missing))
        if problems:
            bad.append((len(missing), f"{case.get('id')}: " + "; ".join(problems)))
    if not bad:
        return [Finding("CT003", "info", f"Mapping complete for all {total} cases.")]
    bad.sort(key=lambda x: -x[0])
    return [Finding(
        "CT003", "error",
        f"Mapping is incomplete or inconsistent in {len(bad)} of {total} input cases.",
        details=[b for _, b in bad],
        hint="mandatory items must never be capped, filtered or outranked; cap optional "
             "items only and report what was cut")]


# ---------------------------------------------------------------------------
# CT004 empty report accepted
# ---------------------------------------------------------------------------

def check_empty_report(adapter: ModuleType) -> List[Finding]:
    if getattr(adapter, "EMPTY_OK", False):
        return []
    data = _empty_lists(adapter.model_output())
    report, _ = _try_parse(adapter, data, adapter.trusted_input())
    if report is None:
        return [Finding("CT004", "info", "A content-free model response is rejected (good).")]
    return [Finding(
        "CT004", "warning",
        "A model response with every list emptied (no regulations, no assessments, no gaps) "
        "is accepted as a valid report.",
        hint="reject reports that omit mapped mandatory items, or require an explicit "
             "'not applicable' entry with a reason")]


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

CHECKS = (check_agent_owned, check_render_injection, check_mapping, check_empty_report)


def run_contract(adapter_path: Path, repo_root: Path) -> List[Finding]:
    """Run all contract checks; imports made by the repo are undone afterwards."""
    modules_before = set(sys.modules)
    path_before = list(sys.path)
    try:
        return _run_contract(adapter_path, repo_root)
    finally:
        for name in set(sys.modules) - modules_before:
            del sys.modules[name]
        sys.path[:] = path_before


def _run_contract(adapter_path: Path, repo_root: Path) -> List[Finding]:
    try:
        adapter = load_adapter(adapter_path, repo_root)
    except Exception as e:
        return [Finding("CT000", "error", f"Adapter failed to load: {type(e).__name__}: {e}",
                        str(adapter_path), details=traceback.format_exc().splitlines()[-6:])]
    findings: List[Finding] = []
    logging.disable(logging.WARNING)  # the repo's own warnings about hostile input are expected
    try:
        for check in CHECKS:
            try:
                findings += check(adapter)
            except Exception as e:  # noqa: PERF203 - one failing check must not stop the rest
                findings.append(Finding(
                    "CT000", "error", f"{check.__name__} crashed: {type(e).__name__}: {e}",
                    details=traceback.format_exc().splitlines()[-6:]))
    finally:
        logging.disable(logging.NOTSET)
    return findings
