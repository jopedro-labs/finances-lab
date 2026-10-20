"""
Terminal UI for rendering portfolio growth projections using Rich.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.core.models import GrowthProjectionResult


class ProjectionPresenter:
    """Renders growth projections into a formatted terminal UI."""

    def __init__(self) -> None:
        self.console = Console()

    def render_summary(self, result: GrowthProjectionResult) -> None:
        """Renders an executive summary panel."""
        init_val = f"€{result.initial_value:,.2f}"
        monthly_val = f"€{result.monthly_contribution:,.2f}"
        cagr_val = (
            f"{result.historical_cagr_pct:.2%}"
            if result.historical_cagr_pct is not None
            else "N/A"
        )

        summary = (
            f"[bold]Initial Capital:[/bold] [bold yellow]{init_val}[/bold yellow]\n"
            f"[bold]Monthly Contribution:[/bold] [bold blue]{monthly_val}[/bold blue]\n"
            f"[bold]Historical CAGR:[/bold] [bold green]{cagr_val}[/bold green]"
        )
        self.console.print(
            Panel(summary, title="[bold cyan]PORTFOLIO PROJECTION SUMMARY[/bold cyan]")
        )

    def render_milestones(
        self, result: GrowthProjectionResult, scenario_name: str = "Primary"
    ) -> None:
        """Renders milestones table for a specific scenario."""
        scenario = next(
            (s for s in result.scenarios if s.name == scenario_name),
            result.scenarios[0],
        )

        table = Table(
            title=f"[bold cyan]Growth Milestones ({scenario.name})[/bold cyan]"
        )
        table.add_column("Year", style="yellow")
        table.add_column("Invested", justify="right")
        table.add_column("Returns", justify="right")
        table.add_column("Total Value (Nominal)", justify="right", style="green")
        table.add_column(
            "Real Value (Adjusted 2% Inflation)", justify="right", style="blue bold"
        )

        for yr in [10, 20, 30]:
            if yr in scenario.milestones:
                ms = scenario.milestones[yr]
                table.add_row(
                    str(ms.year),
                    f"€{ms.total_invested:,.0f}",
                    f"€{ms.compound_interest:,.0f}",
                    f"€{ms.projected_value:,.0f}",
                    f"€{ms.inflation_adjusted_value:,.0f}",
                )

        self.console.print(table)
