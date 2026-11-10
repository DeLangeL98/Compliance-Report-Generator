#!/usr/bin/env python3
"""
SAAF — Structured Audit & Assurance Framework
Internal Audit Compliance Agent CLI
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import get_args

from rich.console import Console
from rich.prompt import Prompt

from config import Config
from saaf.core.agent import ComplianceAgent, ComplianceReportError
from saaf.core.audit_trail import AuditTrail
from saaf.core.llm import PROVIDERS
from saaf.core.models import AuditInput, AuditTopic, Industry, ListedStatus
from saaf.knowledge.regulations import jurisdiction_warning
from saaf.output.formatter import render_references_note, render_report

console = Console()
err_console = Console(stderr=True)

DEFAULT_ALIAS = "Entity A"

DATA_FLOW_WARNING = (
    "[yellow]Warning:[/yellow] company_name is sent verbatim to the configured LLM API. "
    "Use a synthetic name, or --anonymise / --alias NAME to send a placeholder. "
    "Suppress this notice with --yes."
)


def apply_alias(audit_input: AuditInput, alias: str) -> AuditInput:
    """Return a copy of the input that is safe to send: real name replaced by alias."""
    return audit_input.model_copy(update={"company_name": alias})


def restore_real_name(report, real_name: str):
    """Return the report with the real name put back in audit_input (local display only)."""
    restored = report.audit_input.model_copy(update={"company_name": real_name})
    return report.model_copy(update={"audit_input": restored})


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def _prompt_choice(prompt: str, choices: tuple[str, ...]) -> str:
    console.print(f"\n[bold]{prompt}[/bold]")
    for i, c in enumerate(choices, 1):
        console.print(f"  {i:2d}. {c}")

    while True:
        raw = Prompt.ask("Enter number or exact value")
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        elif raw in choices:
            return raw
        console.print("[red]Invalid choice, please try again.[/red]")


def run_interactive() -> AuditInput:
    console.print("\n[bold cyan]SAAF — Compliance Report Generator[/bold cyan]")
    console.print("Answer the following questions to generate your report.\n")

    company_name = Prompt.ask("[bold]Company name[/bold]")

    industry = _prompt_choice(
        "Industry",
        get_args(Industry),
    )

    country = Prompt.ask("[bold]Country / jurisdiction[/bold] (e.g. US, EU, UK, Australia, Singapore)")

    listed_status = _prompt_choice(
        "Listed status",
        get_args(ListedStatus),
    )

    audit_topic = _prompt_choice(
        "Audit topic",
        get_args(AuditTopic),
    )

    return AuditInput(
        company_name=company_name,
        industry=industry,
        country=country,
        listed_status=listed_status,
        audit_topic=audit_topic,
    )


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saaf",
        description="SAAF — Internal Audit Compliance Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py --interactive
  python cli.py --company "Acme Corp" --industry Healthcare --country US \\
                --listed-status Private --audit-topic Cybersecurity
  python cli.py --company "EuroBank" --industry "Financial Services" --country Germany \\
                --listed-status Public --audit-topic "Data Privacy" --output json
        """,
    )

    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Run in interactive prompt mode")

    # Engagement inputs
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--industry", choices=list(get_args(Industry)),
                        help="Industry sector")
    parser.add_argument("--country", help="Country / jurisdiction (e.g. US, UK, Germany)")
    parser.add_argument("--listed-status", dest="listed_status",
                        choices=list(get_args(ListedStatus)),
                        help="Listing status")
    parser.add_argument("--audit-topic", dest="audit_topic",
                        choices=list(get_args(AuditTopic)),
                        help="Audit topic")

    # Output options
    parser.add_argument("--output", choices=["report", "json", "findings"],
                        default="report",
                        help="Output format (default: report); 'findings' exports "
                             "SAAF finding-schema JSON")
    parser.add_argument("--output-file", dest="output_file",
                        help="Save JSON output to this file path")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show testing approaches for each control (report mode only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show which frameworks would be selected without calling the API")
    parser.add_argument("--anonymise", "--anonymize", action="store_true",
                        help=f"Send a placeholder alias (default '{DEFAULT_ALIAS}') to the API "
                             "instead of the company name; the real name stays local")
    parser.add_argument("--alias", metavar="NAME",
                        help="Alias to send to the API in place of the company name (implies --anonymise)")
    parser.add_argument("--yes", "--no-warn", dest="yes", action="store_true",
                        help="Suppress the warning that the company name is sent to the API")
    parser.add_argument("--audit-trail-dir", dest="audit_trail_dir",
                        help="Opt-in: write a per-run JSON record (<report_id>.json) to this directory")
    parser.add_argument("--audit-trail-include-company", action="store_true",
                        help="Keep company name in the audit trail (redacted by default)")
    # Model / endpoint selection (each also has an environment variable; see config.py)
    parser.add_argument("--provider", choices=list(PROVIDERS),
                        help="LLM provider: 'anthropic' (default) or 'openai' for any "
                             "OpenAI-compatible API (env: SAAF_PROVIDER)")
    parser.add_argument("--model",
                        help="Model name (env: SAAF_MODEL; default claude-opus-4-6 for anthropic)")
    parser.add_argument("--base-url", dest="base_url",
                        help="Custom API endpoint, e.g. http://localhost:11434/v1 "
                             "(env: SAAF_BASE_URL)")
    parser.add_argument("--log-level", dest="log_level",
                        choices=["debug", "info", "warning", "error"], default="info",
                        help="Logging verbosity (default: info)")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _configure_logging(level: str) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=level.upper(),
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # anthropic 1.0+ uses httpx2
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _configure_logging(args.log_level)

    # Collect audit input
    if args.interactive:
        audit_input = run_interactive()
    else:
        missing = [f for f, v in [
            ("--company", args.company),
            ("--industry", args.industry),
            ("--country", args.country),
            ("--listed-status", args.listed_status),
            ("--audit-topic", args.audit_topic),
        ] if not v]

        if missing:
            err_console.print(
                f"[red]Missing required arguments: {', '.join(missing)}[/red]\n"
                "Use --interactive for prompted mode, or provide all flags.\n"
                "Run with --help for usage."
            )
            return 1

        audit_input = AuditInput(
            company_name=args.company,
            industry=args.industry,
            country=args.country,
            listed_status=args.listed_status,
            audit_topic=args.audit_topic,
        )

    warning = jurisdiction_warning(audit_input.country)
    if warning:
        err_console.print(f"[yellow]Warning:[/yellow] {warning}")

    # Dry-run: just show the mapping
    if args.dry_run:
        from saaf.core.mapper import FrameworkMapper
        mapping = FrameworkMapper(audit_input).map()
        console.print(f"\n[bold]Dry run — Jurisdiction:[/bold] {mapping.resolved_jurisdiction}")
        console.print(f"[bold]Frameworks identified ({len(mapping.framework_matches)}):[/bold]")
        for m in mapping.framework_matches:
            console.print(f"  • [cyan]{m.full_name}[/cyan]")
            console.print(f"    [dim]{m.rationale}[/dim]")
        console.print()
        return 0

    # Run the agent
    try:
        config = Config(
            provider=args.provider or "",
            model=args.model or "",
            base_url=args.base_url or "",
        )
    except EnvironmentError as e:
        err_console.print(f"[red]Configuration error:[/red] {e}")
        return 1

    # Data flow: the real company name only leaves the machine if not aliased
    real_name = audit_input.company_name
    anonymised = bool(args.anonymise or args.alias)
    if anonymised:
        audit_input = apply_alias(audit_input, args.alias or DEFAULT_ALIAS)
    elif not args.yes:
        err_console.print(DATA_FLOW_WARNING)

    agent = ComplianceAgent(config)
    if args.audit_trail_dir:
        agent.audit_trail = AuditTrail(
            Path(args.audit_trail_dir),
            redact_company=not args.audit_trail_include_company,
        )

    console.print("\n[bold]Generating compliance report...[/bold] ", end="")
    console.print("[dim](this may take 30–60 seconds)[/dim]\n")

    try:
        report, mapping = agent.run(audit_input)
    except ComplianceReportError as e:
        err_console.print(f"[red]Agent error:[/red] {e}")
        if e.raw_response:
            err_console.print("\n[dim]Raw response (first 500 chars):[/dim]")
            err_console.print(e.raw_response[:500])
        return 1

    if anonymised:
        # Real name is restored locally only; it was never sent to the API
        report = restore_real_name(report, real_name)

    # Output
    if args.output in ("json", "findings"):
        if args.output == "findings":
            from saaf.output.findings import report_to_findings
            json_str = json.dumps(report_to_findings(report), indent=2)
        else:
            json_str = report.model_dump_json(indent=2)
        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(json_str)
            console.print(f"[green]Report saved to:[/green] {args.output_file}")
        else:
            print(json_str)
        # Keep stdout pure JSON; surface the note on stderr.
        render_references_note(report, mapping, target=err_console)
    else:
        render_report(report, verbose=args.verbose, mapping=mapping)
        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
            console.print(f"[dim]JSON also saved to: {args.output_file}[/dim]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
