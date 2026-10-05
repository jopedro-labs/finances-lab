"""CLI module for independent fundamental health and quality tier evaluations
featuring rich structured asset cards aligned with portfolio opportunity layouts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.config import DATA_DIR
from src.core.analysis import evaluate_etf_quality, evaluate_stock_quality
from src.core.exceptions import StorageError
from src.core.models import Asset, ETFDetails, StockDetails
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import SqlitePortfolioRepository
from src.infra.database.connection import DEFAULT_DB_PATH
from src.infra.notifications.discord import (
    send_quality_notification,
)
from src.utils.json_loader import load_json_data
from src.utils.logger.logger import logger

app: typer.Typer = typer.Typer(
    help="Independent fundamental health and quality evaluation engine commands."
)
console: Console = Console()


def _format_tier(tier: str) -> Text:
    """Formats quality tier with standard color coding."""
    upper_tier: str = tier.upper()
    if "TIER A" in upper_tier:
        return Text(tier, style="bold green")
    if "TIER B" in upper_tier:
        return Text(tier, style="bold yellow")
    return Text(tier, style="bold red")


def export_quality_report(
    evaluated_assets: list[dict[str, Any]],
    output_dir: Path = Path("output/reports"),
) -> None:
    """Exports independent comprehensive quality evaluation report as HTML."""
    import base64
    from collections import Counter

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Compute KPIs
    total_assets = len(evaluated_assets)
    tiers = Counter(a.get("tier", "Unknown") for a in evaluated_assets)
    valuation_status = Counter(a.get("valuation", "Unknown") for a in evaluated_assets)

    kpis = {
        "total": total_assets,
        "tier_a": tiers.get("Tier A", 0),
        "tier_b": tiers.get("Tier B", 0),
        "tier_c": tiers.get("Tier C", 0),
        "undervalued": valuation_status.get("Undervalued", 0),
        "overvalued": valuation_status.get("Overvalued", 0),
    }

    # Load exposure plots as base64
    plots_dir = Path("output/plots")
    exposure_plots = {}
    for plot_name in [
        "exposure_sector.png",
        "exposure_country.png",
        "exposure_company.png",
    ]:
        plot_path = plots_dir / plot_name
        if plot_path.exists():
            with open(plot_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
                exposure_plots[plot_name.split(".")[0]] = encoded

    html_path: Path = output_dir / "quality_report.html"
    try:
        from src.utils.render import render_html

        render_html(
            "quality_report.html.j2",
            {
                "generated_at": timestamp_str,
                "assets": evaluated_assets,
                "kpis": kpis,
                "exposure_plots": exposure_plots,
            },
            html_path,
        )
        logger.success(f"Successfully exported quality report HTML to '{html_path}'.")
    except Exception as err:
        logger.error(f"Failed to export quality report HTML: {err}")


def save_quality_to_database(
    evaluated_assets: list[dict[str, Any]],
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Persists evaluated fundamental health metrics, quality tier,

    score, and history into SQLite database.
    """
    if not db_path.exists():
        logger.warning(f"Database path not found: {db_path}")
        return

    fetched_at_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(db_path)
        with conn:
            cursor: sqlite3.Cursor = conn.cursor()
            for item in evaluated_assets:
                symbol_str: str = str(item["symbol"])
                asset_type_str: str = str(item["asset_type"])
                quality_tier: str = str(item.get("tier", "Tier C"))
                raw_score: Any = item.get("score")
                quality_score: int = raw_score if isinstance(raw_score, int) else 0
                name_str: str = str(item["name"])
                isin_str: str = str(item.get("isin", ""))

                cursor.execute(
                    "SELECT id FROM assets "
                    "WHERE UPPER(yahoo_ticker) = ? OR UPPER(isin) = ?",
                    (symbol_str.upper(), symbol_str.upper()),
                )
                row: tuple[Any, ...] | None = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        INSERT INTO assets (
                            isin, name, yahoo_ticker,
                            quantity, average_buy_price, asset_type
                        )
                        VALUES (?, ?, ?, 0.0, 0.0, ?)
                        """,
                        (isin_str, name_str, symbol_str, asset_type_str),
                    )
                    last_row_id: int | None = cursor.lastrowid
                    asset_id: int = last_row_id if last_row_id is not None else 0
                else:
                    asset_id = int(row[0])

                if asset_type_str == "ETF":
                    details: ETFDetails | None = item.get("etf_details")
                    ter_pct: float | None = details.ter_pct if details else None
                    holdings_json: str = (
                        json.dumps([h.to_dict() for h in details.holdings])
                        if details and details.holdings
                        else "[]"
                    )
                    sector_json: str = (
                        json.dumps([s.to_dict() for s in details.sector_breakdown])
                        if details and details.sector_breakdown
                        else "[]"
                    )
                    country_json: str = (
                        json.dumps([c.to_dict() for c in details.country_breakdown])
                        if details and details.country_breakdown
                        else "[]"
                    )

                    cursor.execute(
                        """
                        INSERT INTO etf_fundamental_history (
                            asset_id, fetched_at, ter_pct, holdings_json,
                            sector_breakdown_json, country_breakdown_json,
                            quality_tier, quality_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            fetched_at_str,
                            ter_pct,
                            holdings_json,
                            sector_json,
                            country_json,
                            quality_tier,
                            quality_score,
                        ),
                    )
                else:
                    details_stock: StockDetails | None = item.get("stock_details")
                    market_cap: float | None = (
                        details_stock.market_cap if details_stock else None
                    )
                    pe_ratio: float | None = (
                        details_stock.pe_ratio if details_stock else None
                    )
                    forward_pe: float | None = (
                        details_stock.forward_pe if details_stock else None
                    )
                    div_yield: float | None = (
                        details_stock.dividend_yield_pct if details_stock else None
                    )
                    high_52w: float | None = (
                        details_stock.fifty_two_week_high if details_stock else None
                    )
                    low_52w: float | None = (
                        details_stock.fifty_two_week_low if details_stock else None
                    )
                    sector: str | None = details_stock.sector if details_stock else None
                    industry: str | None = (
                        details_stock.industry if details_stock else None
                    )

                    cursor.execute(
                        """
                        INSERT INTO stock_fundamental_history (
                            asset_id, fetched_at, market_cap, pe_ratio,
                            forward_pe, dividend_yield_pct, fifty_two_week_high,
                            fifty_two_week_low, sector, industry,
                            quality_tier, quality_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            fetched_at_str,
                            market_cap,
                            pe_ratio,
                            forward_pe,
                            div_yield,
                            high_52w,
                            low_52w,
                            sector,
                            industry,
                            quality_tier,
                            quality_score,
                        ),
                    )
            # Commit is handled by with conn context manager on success
        conn.close()
        logger.success(
            "Successfully persisted quality evaluation metrics "
            "and history into SQLite database."
        )
    except Exception as err:
        logger.error(
            f"Failed to persist quality evaluation report into database: {err}"
        )


@app.command(name="analyze-quality")
def analyze_quality_cmd(
    ticker: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional ticker symbol or ISIN to analyze. "
                "If omitted, analyzes all target portfolio assets."
            )
        ),
    ] = None,
    targets_file: Annotated[
        Path,
        typer.Option(
            "--targets-file",
            "-t",
            help="Path to JSON file containing target wishlist.",
        ),
    ] = DATA_DIR
    / "portfolio_targets.json",
    notify: Annotated[
        bool,
        typer.Option(
            "--notify",
            help="Dispatch results to Discord webhook if configured.",
        ),
    ] = False,
) -> None:
    """Evaluates absolute quality tiers, comprehensive fundamental metrics,
    diagnostic Bull/Bear cases, and valuation status for target portfolio assets.
    """
    stock_provider: StockProvider = StockProvider()
    etf_provider: ETFProvider = ETFProvider()

    assets: list[Asset] = []

    if targets_file.exists():
        raw_items: list[dict[str, Any]] = load_json_data(targets_file)
        if not raw_items:
            logger.error(f"No assets found in '{targets_file}'.")
            raise typer.Exit(code=1)
        try:
            for item_dict in raw_items:
                assets.append(
                    Asset(
                        name=str(item_dict["name"]),
                        isin=str(item_dict.get("isin", "")),
                        yahoo_ticker=str(item_dict["yahoo_ticker"]),
                        asset_type=str(item_dict["asset_type"]),
                        quantity=0.0,
                        average_buy_price=0.0,
                    )
                )
        except (KeyError, TypeError) as err:
            logger.error(f"Failed to parse assets from '{targets_file}': {err}")
            raise typer.Exit(code=1) from err
    else:
        portfolio_repo: SqlitePortfolioRepository = SqlitePortfolioRepository()
        try:
            assets = portfolio_repo.load_assets()
        except StorageError as err:
            logger.error(f"Failed to load assets from database: {err}")
            raise typer.Exit(code=1) from err

    if not assets:
        logger.warning("No assets found for quality analysis.")
        return

    target_assets: list[Asset] = assets
    if ticker:
        clean_ticker: str = ticker.strip().upper()
        target_assets = [
            a
            for a in assets
            if a.yahoo_ticker.upper() == clean_ticker
            or (a.isin and a.isin.upper() == clean_ticker)
        ]
        if not target_assets:
            console.print(f"[red]Asset '{ticker}' not found in target list.[/red]")
            raise typer.Exit(code=1)

    console.print(
        "\n[bold cyan]INDEPENDENT FUNDAMENTAL HEALTH & QUALITY ANALYSIS "
        "[/bold cyan]\n"
    )

    evaluated_report_items: list[dict[str, Any]] = []

    for asset in target_assets:
        is_etf: bool = asset.asset_type.upper() == "ETF"
        symbol: str = asset.yahoo_ticker
        name: str = asset.name
        isin: str = asset.isin

        diagnostic: dict[str, Any] = {}
        val_lines: str = ""
        border_style: str = "yellow"

        item_data: dict[str, Any] = {
            "name": name,
            "symbol": symbol,
            "isin": isin,
            "asset_type": asset.asset_type.upper(),
        }

        if is_etf:
            etf_details: ETFDetails | None = etf_provider.get_details(asset)
            item_data["etf_details"] = etf_details
            if etf_details:
                diagnostic = evaluate_etf_quality(etf_details)
                ter_val: float | None = etf_details.ter_pct
                ter_str: str = f"{ter_val:.2f}%" if ter_val is not None else "N/A"

                holdings_str: str = (
                    ", ".join(
                        [
                            f"{h.name} ({h.weight_pct:.1f}%)"
                            for h in etf_details.holdings[:5]
                        ]
                    )
                    if etf_details.holdings
                    else "N/A"
                )

                sectors_str: str = (
                    ", ".join(
                        [
                            f"{s.sector_name} ({s.weight_pct:.1f}%)"
                            for s in etf_details.sector_breakdown[:4]
                        ]
                    )
                    if etf_details.sector_breakdown
                    else "N/A"
                )

                countries_str: str = (
                    ", ".join(
                        [
                            f"{c.country_name} ({c.weight_pct:.1f}%)"
                            for c in etf_details.country_breakdown[:4]
                        ]
                    )
                    if etf_details.country_breakdown
                    else "N/A"
                )

                item_data.update(
                    {
                        "ter_str": ter_str,
                        "holdings_str": holdings_str,
                        "sectors_str": sectors_str,
                        "countries_str": countries_str,
                    }
                )

                ter_label: str = (
                    "  [bold white]- Total Expense Ratio (TER):[/bold white]"
                )
                val_lines = (
                    f"• [bold]Valuation & ETF Structure Metrics:[/bold]\n"
                    f"{ter_label} {ter_str}\n"
                    f"  [bold white]- Top Holdings:[/bold white] {holdings_str}\n"
                    f"  [bold white]- Sector Breakdown:[/bold white] {sectors_str}\n"
                    f"  [bold white]- Country Breakdown:[/bold white] {countries_str}"
                )
            else:
                diagnostic = {
                    "score": 0,
                    "tier": "Tier C",
                    "bull_case": ["N/A"],
                    "bear_case": ["ETF metadata unavailable"],
                    "valuation_status": "N/A",
                }
                val_lines = (
                    "• [bold]Valuation & ETF Structure Metrics:[/bold]\n"
                    "  - [red]Metadata unavailable[/red]"
                )
        else:
            stock_details: StockDetails | None = stock_provider.get_details(asset)
            item_data["stock_details"] = stock_details
            if stock_details:
                diagnostic = evaluate_stock_quality(stock_details)
                tr_pe: float | None = stock_details.pe_ratio
                fw_pe: float | None = stock_details.forward_pe
                peg: float | None = stock_details.peg_ratio
                pb: float | None = stock_details.price_to_book
                div_yield: float | None = stock_details.dividend_yield_pct
                beta: float | None = stock_details.beta
                margin: float | None = stock_details.profit_margins_pct
                rev_growth: float | None = stock_details.revenue_growth_pct
                earn_growth: float | None = stock_details.earnings_growth_pct
                debt_eq: float | None = stock_details.total_debt_to_equity
                high_52w: float | None = stock_details.fifty_two_week_high
                low_52w: float | None = stock_details.fifty_two_week_low

                tr_str: str = f"{tr_pe:.1f}" if tr_pe else "N/A"
                fw_str: str = f"{fw_pe:.1f}" if fw_pe else "N/A"
                peg_str: str = f"{peg:.2f}" if peg else "N/A"
                pb_str: str = f"{pb:.2f}" if pb else "N/A"
                div_str: str = f"{div_yield:.2f}%" if div_yield else "N/A"
                beta_str: str = f"{beta:.2f}" if beta else "N/A"
                margin_str: str = f"{margin:.1f}%" if margin else "N/A"
                rev_str: str = f"{rev_growth:.1f}%" if rev_growth else "N/A"
                earn_str: str = f"{earn_growth:.1f}%" if earn_growth else "N/A"
                debt_str: str = f"{debt_eq:.1f}" if debt_eq else "N/A"
                low_str: str = f"{low_52w:,.2f} EUR" if low_52w else "N/A"
                peak_str: str = f"{high_52w:,.2f} EUR" if high_52w else "N/A"

                item_data.update(
                    {
                        "tr_str": tr_str,
                        "fw_str": fw_str,
                        "peg_str": peg_str,
                        "pb_str": pb_str,
                        "div_str": div_str,
                        "beta_str": beta_str,
                        "margin_str": margin_str,
                        "rev_str": rev_str,
                        "earn_str": earn_str,
                        "debt_str": debt_str,
                        "low_str": low_str,
                        "peak_str": peak_str,
                    }
                )

                val_lines = (
                    "• [bold underline]Valuation & Fundamental Metrics:"
                    "[/bold underline]\n"
                    f"  [bold white]- Trailing P/E:[/bold white] {tr_str} | "
                    f"[bold white]Forward P/E:[/bold white] {fw_str} | "
                    f"[bold white]PEG:[/bold white] {peg_str} | P/B: {pb_str}\n"
                    f"  [bold white]- Div Yield:[/bold white] {div_str} | "
                    f"[bold white]Beta:[/bold white] {beta_str} | "
                    f"[bold white]Profit Margin:[/bold white] {margin_str}\n"
                    f"  [bold white]- Rev Growth:[/bold white] {rev_str} | "
                    f"[bold white]Earn Growth:[/bold white] {earn_str} | "
                    f"[bold white]Debt/Equity:[/bold white] {debt_str}\n"
                    f"  [bold white]- 52w Range (Low / High):[/bold white] {low_str} / "
                    f"{peak_str}"
                )
            else:
                diagnostic = {
                    "score": 0,
                    "tier": "Tier C",
                    "bull_case": ["N/A"],
                    "bear_case": ["Fundamental data unavailable"],
                    "valuation_status": "N/A",
                }
                val_lines = (
                    "• [bold]Valuation & Fundamental Metrics:[/bold]\n"
                    "  - [red]Fundamental data unavailable[/red]"
                )

        tier_val: str = str(diagnostic.get("tier", "Tier B"))
        tier_text: Text = _format_tier(tier_val)
        raw_score_val: Any = diagnostic.get("score")
        score_val: int = raw_score_val if isinstance(raw_score_val, int) else 0
        valuation_status: str = str(diagnostic.get("valuation_status", "N/A"))

        item_data.update(
            {
                "tier": tier_val,
                "score": score_val,
                "valuation_status": valuation_status,
                "bull_case": diagnostic.get("bull_case", []),
                "bear_case": diagnostic.get("bear_case", []),
            }
        )
        evaluated_report_items.append(item_data)

        if "Tier A" in tier_val:
            border_style = "green"
        elif "Tier C" in tier_val:
            border_style = "red"

        bull_bullets: str = "".join(
            [f"  • {item}\n" for item in diagnostic.get("bull_case", [])]
        )
        bear_bullets: str = "".join(
            [f"  • {item}\n" for item in diagnostic.get("bear_case", [])]
        )

        type_str: str = asset.asset_type.upper()
        divider: str = "─" * 67
        panel_content: str = (
            f"[bold]Asset Type:[/bold] [bold blue]{type_str}[/bold blue]  │  "
            f"[bold]Quality Tier:[/bold] {tier_text.markup}  │  "
            f"[bold]Quality Score:[/bold] [bold blue]{score_val}/100[/bold blue]\n"
            f"{divider}\n"
            f"{val_lines}\n"
            f"{divider}\n"
            "[bold green]🟢 Bull Case (Catalysts & Strengths):[/bold green]\n"
            f"{bull_bullets}\n"
            "[bold red]🔴 Bear Case (Risks & Pressures):[/bold red]\n"
            f"{bear_bullets}\n"
            f"{divider}\n"
            "[bold]Valuation Status:[/bold] "
            f"[bold yellow]{valuation_status}[/bold yellow]"
        )

        card: Panel = Panel(
            panel_content,
            title=f"[bold cyan]{name} ({symbol})[/bold cyan]",
            border_style=border_style,
            expand=False,
        )
        console.print(card)
        console.print()

    export_quality_report(evaluated_report_items)
    save_quality_to_database(evaluated_report_items)

    # Dispatch Discord notification if explicitly requested
    if notify:
        send_quality_notification(evaluated_report_items)
