"""CLI command handler for generating executive portfolio reports."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from src.config import DATA_DIR
from src.infra.database.connection import DEFAULT_DB_PATH

app: typer.Typer = typer.Typer(help="Generate HTML executive portfolio reports.")


@app.callback()
def report_callback() -> None:
    """Report CLI module callback."""


@app.command(name="generate")
def generate_report(
    db_path: Annotated[
        Path,
        typer.Option("--db-path", "-d", help="Path to finances SQLite database file."),
    ] = Path(DEFAULT_DB_PATH),
    config_path: Annotated[
        Path,
        typer.Option(
            "--config", "-c", help="Path to portfolio JSON configuration file."
        ),
    ] = DATA_DIR
    / "portfolio.json",
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where the HTML report will be written.",
        ),
    ] = Path("output/reports"),
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser", help="Skip opening the HTML report in the browser."
        ),
    ] = False,
    monthly_contribution: Annotated[
        float,
        typer.Option(
            "--monthly-contribution",
            "-m",
            help="Monthly investment contribution used in growth projections (EUR).",
        ),
    ] = 500.0,
) -> None:
    """Generates a dark-theme HTML executive portfolio report."""
    from src.infra.report_generator import PortfolioReportGenerator

    console = Console()

    try:
        generator = PortfolioReportGenerator(
            db_path=db_path,
            config_path=config_path,
            output_dir=output_dir,
            monthly_contribution=monthly_contribution,
        )
        html_path = generator.generate(open_browser=not no_browser)
        console.print(
            f"[bold green]Report generated successfully:[/bold green]\n"
            f"  HTML: {html_path}"
        )
    except Exception as err:
        console.print(f"[bold red]Error:[/bold red] Failed to generate report: {err}")
        raise typer.Exit(code=1) from err
