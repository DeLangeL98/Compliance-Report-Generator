"""Command line: ``python -m sentinel [all|static|contract] [options]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sentinel import __version__
from sentinel.contract import run_contract
from sentinel.report import (
    SEVERITIES,
    at_least,
    to_github_annotations,
    to_json,
    to_markdown,
    to_sarif,
    to_text,
)
from sentinel.static_checks import DEFAULT_EXCLUDES, run_static


def _load_config(root: Path, path: str | None) -> dict:
    cfg_path = Path(path) if path else root / "sentinel.toml"
    if not cfg_path.is_file():
        if path:
            raise SystemExit(f"sentinel: config not found: {cfg_path}")
        return {}
    import tomllib  # stdlib; imported here so import sorting is stable across Ruff versions

    with open(cfg_path, "rb") as f:
        return tomllib.load(f)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sentinel", description="SAAF Sentinel hardening checks")
    p.add_argument("mode", nargs="?", choices=("all", "static", "contract"), default="all")
    p.add_argument("--root", default=".", help="repository root (default: .)")
    p.add_argument("--config", help="path to sentinel.toml (default: <root>/sentinel.toml)")
    p.add_argument("--format", choices=("text", "github", "json", "sarif", "markdown"),
                   default="text")
    p.add_argument("--sarif-out", help="also write SARIF to this file")
    p.add_argument("--summary-out", help="also append a Markdown summary to this file")
    p.add_argument("--fail-on", choices=SEVERITIES + ("never",),
                   help="exit 1 if any finding is at or above this severity (default: error)")
    p.add_argument("--include-tests", action="store_true", help="also scan tests/ directories")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    cfg = _load_config(root, args.config)
    static_cfg = cfg.get("static", {})
    contract_cfg = cfg.get("contract", {})
    fail_on = args.fail_on or cfg.get("sentinel", {}).get("fail-on", "error")

    findings = []
    if args.mode in ("all", "static"):
        findings += run_static(
            root,
            excludes=tuple(DEFAULT_EXCLUDES) + tuple(static_cfg.get("exclude", ())),
            include_tests=args.include_tests or static_cfg.get("include-tests", False),
            disable=static_cfg.get("disable", ()),
            allow_action_owners=static_cfg.get("allow-action-owners", ("SAAF-Project",)),
        )
    if args.mode in ("all", "contract"):
        adapter = contract_cfg.get("adapter")
        if adapter:
            contract = run_contract(root / adapter, root)
            findings += contract
            # SEN005 is a static guess; CT001 is the behavioural proof. When CT001 ran
            # and found no leak, keep SEN005 as a note only.
            ct001_ran = any(f.rule == "CT001" for f in contract)
            ct001_leaks = any(f.rule == "CT001" and f.severity == "error" for f in contract)
            if ct001_ran and not ct001_leaks:
                for f in findings:
                    if f.rule == "SEN005":
                        f.severity = "info"
                        f.message += " (CT001 passed: agent-owned fields are overwritten.)"
        elif args.mode == "contract":
            print("sentinel: no [contract] adapter configured in sentinel.toml", file=sys.stderr)
            return 2

    render = {"text": to_text, "github": to_github_annotations, "json": to_json,
              "markdown": to_markdown, "sarif": lambda f: to_sarif(f, __version__)}[args.format]
    shown = findings if args.format in ("text", "json") else at_least(findings, "warning")
    print(render(shown))
    if args.format == "github":  # human-readable log as well as annotations
        print(to_text(findings), file=sys.stderr)
    if args.sarif_out:
        Path(args.sarif_out).write_text(to_sarif(at_least(findings, "warning"), __version__),
                                        encoding="utf-8")
    if args.summary_out:
        with open(args.summary_out, "a", encoding="utf-8") as f:
            f.write(to_markdown(at_least(findings, "warning")))

    if fail_on == "never":
        return 0
    return 1 if at_least(findings, fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
