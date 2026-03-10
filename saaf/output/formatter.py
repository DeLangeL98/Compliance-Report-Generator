"""
Rich-based CLI report renderer.
"""

from __future__ import annotations

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from saaf.core.models import ComplianceReport, ControlObjective

console = Console()

# Risk rating colour map
_RISK_COLOUR = {
    "Critical": "bold red",
    "High": "bold orange3",
    "Medium": "yellow",
    "Low": "green",
}

_MANDATORY_COLOUR = "bold red"
_OPTIONAL_COLOUR = "dim"


def _risk_badge(rating: str) -> Text:
    colour = _RISK_COLOUR.get(rating, "white")
    return Text(f"[{rating}]", style=colour)


def render_report(report: ComplianceReport, *, verbose: bool = False) -> None:
    """Render the full compliance report to the terminal."""
    ai = report.audit_input

    # ── Header ────────────────────────────────────────────────────────────
    header_text = Text()
    header_text.append("SAAF Compliance Report\n", style="bold white")
    header_text.append(f"{ai.company_name}  |  ", style="bold cyan")
    header_text.append(f"{ai.audit_topic}  |  {ai.industry}  |  {ai.country}  |  {ai.listed_status}",
                       style="cyan")

    console.print()
    console.print(Panel(header_text, box=box.DOUBLE, padding=(0, 2)))
    console.print(f"  Report ID: [dim]{report.report_id}[/dim]")
    console.print(f"  Generated: [dim]{report.generated_at}[/dim]")
    console.print()

    # ── Overall risk ──────────────────────────────────────────────────────
    summary = report.gap_risk_summary
    overall_colour = _RISK_COLOUR.get(summary.overall_risk_rating, "white")
    console.print(
        Panel(
            f"[{overall_colour}]Overall Risk Rating: {summary.overall_risk_rating}[/{overall_colour}]\n\n"
            f"[italic]{summary.executive_summary}[/italic]",
            title="[bold]Executive Summary[/bold]",
            border_style=overall_colour,
            padding=(0, 2),
        )
    )
    console.print()

    # ── Mandatory regulations ─────────────────────────────────────────────
    console.rule("[bold]Mandatory Regulations[/bold]")
    console.print()

    for reg in report.mandatory_regulations:
        style = _MANDATORY_COLOUR if reg.mandatory else _OPTIONAL_COLOUR
        label = "[MANDATORY]" if reg.mandatory else "[ADVISORY]"
        console.print(
            f"  [{style}]{label}[/{style}] [bold]{reg.regulation_name}[/bold]  "
            f"[dim]({reg.jurisdiction})[/dim]"
        )
        if reg.applicable_sections:
            console.print(
                "    Sections: " + ", ".join(f"[cyan]{s}[/cyan]" for s in reg.applicable_sections)
            )
        if reg.compliance_notes:
            console.print(f"    [dim]{reg.compliance_notes}[/dim]")
        console.print()

    # ── Framework assessments ─────────────────────────────────────────────
    console.rule("[bold]Framework Assessments[/bold]")

    for fw in report.framework_assessments:
        risk_colour = _RISK_COLOUR.get(fw.risk_rating, "white")
        fw_header = Text()
        fw_header.append(f"  {fw.framework_name}", style="bold")
        fw_header.append(f"   Risk: ", style="")
        fw_header.append(fw.risk_rating, style=risk_colour)

        console.print()
        console.print(fw_header)
        console.print(f"  [dim]{fw.applicability_rationale}[/dim]")
        console.print()

        # Control objectives table
        if fw.control_objectives:
            table = Table(
                show_header=True,
                header_style="bold dim",
                box=box.SIMPLE_HEAVY,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("Control ID", style="cyan", no_wrap=True, min_width=14)
            table.add_column("Description", ratio=3)
            table.add_column("Source", style="dim", ratio=1)
            table.add_column("Priority", justify="center", no_wrap=True)

            for ctrl in fw.control_objectives:
                p_colour = _RISK_COLOUR.get(ctrl.priority, "white")
                table.add_row(
                    ctrl.control_id,
                    ctrl.description,
                    ctrl.requirement_source,
                    Text(ctrl.priority, style=p_colour),
                )

            console.print(table)

            if verbose:
                console.print()
                for ctrl in fw.control_objectives:
                    _render_control_detail(ctrl)

        # Key gaps
        if fw.key_gaps:
            console.print("  [bold]Key Gaps:[/bold]")
            for i, gap in enumerate(fw.key_gaps, 1):
                console.print(f"    {i}. {gap}")
        console.print()

    # ── Gap & risk summary ────────────────────────────────────────────────
    console.rule("[bold]Gap & Risk Summary[/bold]")
    console.print()

    if summary.critical_gaps:
        console.print("  [bold red]Critical Gaps:[/bold red]")
        for i, gap in enumerate(summary.critical_gaps, 1):
            console.print(f"    {i}. [red]{gap}[/red]")
        console.print()

    if summary.recommended_priority_actions:
        console.print("  [bold]Priority Actions:[/bold]")
        for i, action in enumerate(summary.recommended_priority_actions, 1):
            console.print(f"    {i}. {action}")
        console.print()

    effort_colour = _RISK_COLOUR.get(summary.estimated_remediation_effort, "white")
    console.print(
        f"  Estimated Remediation Effort: "
        f"[{effort_colour}]{summary.estimated_remediation_effort}[/{effort_colour}]"
    )
    console.print()

    # ── Disclaimer ────────────────────────────────────────────────────────
    console.print(Panel(
        f"[dim]{report.disclaimer}[/dim]",
        title="[dim]Disclaimer[/dim]",
        border_style="dim",
        padding=(0, 2),
    ))
    console.print()


def _render_control_detail(ctrl: ControlObjective) -> None:
    """Render expanded detail for a single control objective (verbose mode)."""
    p_colour = _RISK_COLOUR.get(ctrl.priority, "white")
    console.print(
        Panel(
            f"[bold]{ctrl.description}[/bold]\n\n"
            f"[dim]Source:[/dim] {ctrl.requirement_source}\n"
            f"[dim]Testing:[/dim] {ctrl.testing_approach}\n"
            f"[dim]Priority:[/dim] [{p_colour}]{ctrl.priority}[/{p_colour}]",
            title=f"[cyan]{ctrl.control_id}[/cyan]",
            padding=(0, 2),
            expand=False,
        )
    )
