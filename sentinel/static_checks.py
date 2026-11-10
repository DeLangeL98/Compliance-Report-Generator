"""Zero-config static checks (SEN0xx). Standard library only.

Each check encodes a weakness found in a real SAAF agent (see FINDINGS-*.md).
They are heuristics: a hit means "look here", and a reviewed false positive is
silenced on its line with ``# sentinel: ignore[SEN00X]`` (or a bare
``# sentinel: ignore``).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Set

from sentinel.report import Finding

DEFAULT_EXCLUDES = (
    ".git", ".venv", "venv", "env", "node_modules", "build", "dist",
    "site-packages", "__pycache__", ".tox", ".mypy_cache", ".ruff_cache",
)
_IGNORE_RE = re.compile(r"#\s*sentinel:\s*ignore(?:\[([A-Z0-9_, ]+)\])?")
_SHA_RE = re.compile(r"@[0-9a-f]{40}\b")
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^\s'\"#]+)")

_RICH_PRINTERS = {"print", "log", "rule"}
_RICH_MARKUP_CTORS = {"Panel"}
_SAFE_WRAPPERS = {"escape", "Text", "repr", "len", "int", "float", "round"}
_BACKOFF_HINTS = ("sleep", "backoff", "wait", "jitter", "retry_after")
_STOP_KEYS = {"stop_reason", "finish_reason"}
_STOP_VALUES = {"max_tokens", "length", "refusal", "content_filter", "end_turn", "stop"}


# ---------------------------------------------------------------------------
# File discovery and suppression
# ---------------------------------------------------------------------------

def iter_python_files(root: Path, excludes: Sequence[str], include_tests: bool) -> Iterator[Path]:
    for p in sorted(root.rglob("*.py")):
        parts = p.relative_to(root).parts
        if any(part in excludes for part in parts):
            continue
        if not include_tests and any(part in ("tests", "test") for part in parts[:-1]):
            continue
        yield p


def _suppressed(lines: List[str], lineno: Optional[int], rule: str) -> bool:
    if not lineno or lineno > len(lines):
        return False
    m = _IGNORE_RE.search(lines[lineno - 1])
    if not m:
        return False
    return m.group(1) is None or rule in {r.strip() for r in m.group(1).split(",")}


def _call_name(node: ast.AST) -> str:
    """Last dotted component of a call target: ``rich.markup.escape`` -> ``escape``."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _walk_no_nested_defs(node: ast.AST) -> Iterator[ast.AST]:
    """ast.walk that does not descend into nested functions/classes/lambdas."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))


# ---------------------------------------------------------------------------
# SEN001 markup injection
# ---------------------------------------------------------------------------

def _imports_rich(tree: ast.Module) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] == "rich" for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "rich":
            return True
    return False


_STYLE_NAME_RE = re.compile(r"(colou?r|style|label|badge)$|^[a-z_]$", re.IGNORECASE)


def _risky_interpolations(node: ast.AST) -> List[str]:
    """Sources of interpolated values that are not escaped.

    Skips numeric formatting (``{n:3d}``), constants, escaped/wrapped calls, and
    bare local names that are evidently style tokens or loop counters
    (``overall_colour``, ``style``, ``i``); those are agent-controlled.
    """
    out: List[str] = []
    if isinstance(node, ast.JoinedStr):
        for v in node.values:
            if not isinstance(v, ast.FormattedValue) or v.format_spec is not None:
                continue
            val = v.value
            if isinstance(val, ast.Constant):
                continue
            if isinstance(val, ast.Call) and _call_name(val) in _SAFE_WRAPPERS:
                continue
            if isinstance(val, ast.Name) and _STYLE_NAME_RE.search(val.id):
                continue
            src = ast.unparse(val)
            if src not in out:
                out.append(src)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        out = _risky_interpolations(node.left)
        out += [s for s in _risky_interpolations(node.right) if s not in out]
    return out


def check_markup_injection(tree: ast.Module, rel: str) -> List[Finding]:
    if not _imports_rich(tree):
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if any(k.arg == "markup" and isinstance(k.value, ast.Constant) and k.value.value is False
               for k in n.keywords):
            continue
        candidates: List[ast.AST] = []
        if name in _RICH_PRINTERS and isinstance(n.func, ast.Attribute):
            candidates = list(n.args)
        elif name in _RICH_MARKUP_CTORS:
            candidates = list(n.args) + [k.value for k in n.keywords if k.arg in ("title", "subtitle")]
        elif name == "add_row":
            for a in n.args:  # table cells given as plain str are parsed as markup
                if isinstance(a, (ast.Attribute, ast.Name, ast.Subscript)):
                    out.append(Finding(
                        "SEN001", "warning",
                        f"Table cell `{ast.unparse(a)}` is rendered as Rich markup.",
                        rel, n.lineno,
                        hint="pass Text(value) or rich.markup.escape(value) for untrusted text"))
                    break
            continue
        risky: List[str] = []
        for c in candidates:
            risky += [s for s in _risky_interpolations(c) if s not in risky]
        if risky:
            shown = ", ".join(f"`{s}`" for s in risky[:4]) + (" ..." if len(risky) > 4 else "")
            out.append(Finding(
                "SEN001", "warning",
                f"{shown} interpolated into a Rich markup string; text containing "
                "'[/x]' crashes the render and '[link=...]' injects links.",
                rel, n.lineno,
                hint="wrap with rich.markup.escape(...), build a Text(), or pass markup=False"))
    return out


# ---------------------------------------------------------------------------
# SEN002 retry without backoff
# ---------------------------------------------------------------------------

def _is_retry_loop(loop: ast.AST) -> bool:
    if isinstance(loop, ast.While):
        return True
    return (isinstance(loop, ast.For) and isinstance(loop.iter, ast.Call)
            and _call_name(loop.iter) == "range")


def _handler_falls_through(h: ast.ExceptHandler) -> bool:
    last = h.body[-1] if h.body else None
    if isinstance(last, ast.Continue):
        return True
    if isinstance(last, (ast.Raise, ast.Return, ast.Break)):
        return False
    if isinstance(last, ast.If):  # `if not retryable: raise` then fall through
        return True
    return True


def check_retry_backoff(tree: ast.Module, rel: str) -> List[Finding]:
    out = []
    for loop in ast.walk(tree):
        if not isinstance(loop, (ast.For, ast.While)) or not _is_retry_loop(loop):
            continue
        body = list(_walk_no_nested_defs(loop))
        tries = [n for n in body if isinstance(n, ast.Try)]
        if not tries or not any(_handler_falls_through(h) for t in tries for h in t.handlers):
            continue
        has_call_in_try = any(isinstance(x, ast.Call) for t in tries for s in t.body
                              for x in ast.walk(s))
        if not has_call_in_try:
            continue
        if any(isinstance(x, ast.Call) and any(h in _call_name(x).lower() for h in _BACKOFF_HINTS)
               for x in body):
            continue
        out.append(Finding(
            "SEN002", "warning",
            "Loop catches an error and tries again with no sleep/backoff; under rate limits or "
            "overload this hammers the provider and burns the retry budget in milliseconds.",
            rel, loop.lineno,
            hint="sleep with exponential backoff + jitter, honour Retry-After, and treat 429 "
                 "as retryable"))
    return out


# ---------------------------------------------------------------------------
# SEN003 silent truncation
# ---------------------------------------------------------------------------

def _fixed_head_slice(node: ast.AST) -> Optional[str]:
    if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
        return None
    s = node.slice
    if s.lower is not None or s.step is not None or s.upper is None:
        return None
    up = s.upper
    if isinstance(up, ast.Constant) and isinstance(up.value, int):
        return str(up.value)
    if isinstance(up, ast.Name) and up.id.isupper():
        return up.id
    return None


def check_silent_truncation(tree: ast.Module, rel: str) -> List[Finding]:
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        logs = any(isinstance(x, ast.Call) and _call_name(x) in ("warning", "warn", "error")
                   for x in _walk_no_nested_defs(fn))
        for n in _walk_no_nested_defs(fn):
            if isinstance(n, ast.Return) and n.value is not None:
                cap = _fixed_head_slice(n.value)
                if cap and not logs:
                    out.append(Finding(
                        "SEN003", "warning",
                        f"`{fn.name}` returns only the first {cap} items and never warns about "
                        "what it dropped. In a mapper this silently removes mandatory scope.",
                        rel, n.lineno,
                        hint="never cap mandatory items; if a cap is needed, apply it to "
                             "optional items only and log/report what was cut"))
    return out


# ---------------------------------------------------------------------------
# SEN004 unchecked stop reason (repository-wide)
# ---------------------------------------------------------------------------

def _is_stop_key(node: Optional[ast.AST]) -> bool:
    return isinstance(node, ast.Constant) and node.value in _STOP_KEYS


def _stop_refs(tree: ast.Module) -> List[int]:
    """Lines that read a stop/finish reason: ``x.stop_reason``, ``d["finish_reason"]``,
    ``d.get("finish_reason")`` or a dict entry keyed by it."""
    refs = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr in _STOP_KEYS:
            refs.append(n.lineno)
        elif isinstance(n, ast.Subscript) and _is_stop_key(n.slice):
            refs.append(n.lineno)
        elif (isinstance(n, ast.Call) and _call_name(n) == "get" and n.args
              and _is_stop_key(n.args[0])):
            refs.append(n.lineno)
        elif isinstance(n, ast.Dict) and any(_is_stop_key(k) for k in n.keys):
            refs.append(next(k.lineno for k in n.keys if _is_stop_key(k)))
    return refs


def _stop_compared(tree: ast.Module) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            for c in ast.walk(n):
                if isinstance(c, ast.Constant) and c.value in _STOP_VALUES:
                    return True
        if isinstance(n, ast.Match):
            for c in ast.walk(n):
                if isinstance(c, ast.Constant) and c.value in _STOP_VALUES:
                    return True
    return False


# ---------------------------------------------------------------------------
# SEN005 model output splatted into a model class
# ---------------------------------------------------------------------------

def check_model_output_splat(tree: ast.Module, rel: str) -> List[Finding]:
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parsed: Set[str] = set()
        for n in _walk_no_nested_defs(fn):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                    and _call_name(n.value) in ("loads", "model_validate_json")
                    and "json" in ast.unparse(n.value.func)):
                parsed |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        if not parsed:
            continue
        for n in _walk_no_nested_defs(fn):
            if not isinstance(n, ast.Call):
                continue
            splats = [k for k in n.keywords if k.arg is None
                      and isinstance(k.value, ast.Name) and k.value.id in parsed]
            via_validate = (_call_name(n) == "model_validate" and n.args
                            and isinstance(n.args[0], ast.Name) and n.args[0].id in parsed)
            if splats or via_validate:
                out.append(Finding(
                    "SEN005", "warning",
                    f"Model JSON is passed straight into `{ast.unparse(n.func)}`; any field "
                    "with a default (ids, timestamps, echoed inputs, flags) can be set by the "
                    "model.",
                    rel, n.lineno,
                    hint="overwrite agent-owned fields after validation (or exclude them from "
                         "the model schema) and prove it with contract check CT001"))
    return out


# ---------------------------------------------------------------------------
# SEN006 unpinned GitHub Actions
# ---------------------------------------------------------------------------

def check_workflows(root: Path, allow_owners: Iterable[str]) -> List[Finding]:
    allow = {o.lower() for o in allow_owners}
    out = []
    files = sorted(root.glob(".github/workflows/*.y*ml")) + sorted(root.glob("**/action.y*ml"))
    for wf in files:
        if any(part in DEFAULT_EXCLUDES for part in wf.relative_to(root).parts):
            continue
        rel = wf.relative_to(root).as_posix()
        lines = wf.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            m = _USES_RE.match(line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith(("./", "docker://")) or "@" not in ref:
                continue
            owner = ref.split("/")[0].lower()
            if owner in allow or _SHA_RE.search(ref):
                continue
            if _suppressed(lines, i, "SEN006"):
                continue
            first_party = owner in ("actions", "github")
            out.append(Finding(
                "SEN006", "info" if first_party else "warning",
                f"`{ref}` is pinned to a movable tag/branch"
                + ("" if first_party else " (third-party action)") + ".",
                rel, i,
                hint="pin to the full commit SHA and keep the tag in a comment, "
                     "e.g. uses: owner/action@<sha>  # v2"))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

PER_FILE = (check_markup_injection, check_retry_backoff, check_silent_truncation,
            check_model_output_splat)


def run_static(
    root: Path,
    *,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
    include_tests: bool = False,
    disable: Iterable[str] = (),
    allow_action_owners: Iterable[str] = ("SAAF-Project",),
) -> List[Finding]:
    root = Path(root).resolve()
    disabled = set(disable)
    findings: List[Finding] = []
    stop_refs: List[tuple] = []
    stop_checked = False

    for path in iter_python_files(root, excludes, include_tests):
        rel = path.relative_to(root).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src, filename=rel)
        except SyntaxError as e:
            findings.append(Finding("SEN000", "info", f"Could not parse: {e.msg}", rel, e.lineno))
            continue
        lines = src.splitlines()
        for check in PER_FILE:
            findings.extend(
                f for f in check(tree, rel)
                if f.rule not in disabled and not _suppressed(lines, f.line, f.rule)
            )
        refs = [ln for ln in _stop_refs(tree) if not _suppressed(lines, ln, "SEN004")]
        stop_refs += [(rel, ln) for ln in refs]
        stop_checked = stop_checked or _stop_compared(tree)

    if stop_refs and not stop_checked and "SEN004" not in disabled:
        rel, ln = stop_refs[0]
        findings.append(Finding(
            "SEN004", "warning",
            "The provider's stop/finish reason is read but no code compares it with "
            "'max_tokens'/'length'/'refusal'; truncated or refused output is parsed as if "
            "it were a complete answer.",
            rel, ln,
            details=list(dict.fromkeys(f"{r}:{n}" for r, n in stop_refs)),
            hint="branch on the stop reason before parsing: raise a clear 'truncated' or "
                 "'refused' error"))

    if "SEN006" not in disabled:
        findings += check_workflows(root, allow_action_owners)
    return findings
