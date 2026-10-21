"""CLI entry point for the finances application powered by Typer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.cli.dashboard import app as dashboard_app
from src.cli.fundamentals import sync_portfolio_fundamentals
from src.cli.opportunity import _run_rebalance, recommend_rebalance
from src.cli.projection_presenter import ProjectionPresenter
from src.cli.quality import analyze_quality_cmd
from src.cli.report import app as report_app
from src.config import DATA_DIR, settings
from src.core.exposure import ExposureEngine
from src.core.models import (
    Asset,
    ETFDetails,
    ETFMarketData,
    GrowthProjectionResult,
    PortfolioSnapshot,
    Quotation,
    StockDetails,
)
from src.core.projections import ProjectionEngine
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import (
    SqliteHistoryRepository,
    SqlitePortfolioRepository,
)
from src.core.snapshot import get_snapshot, save_snapshot
from src.infra.database.connection import DEFAULT_DB_PATH
from src.infra.gdrive.service import GDriveService
from src.utils.graphics.allocation import generate_exposure_pie_chart
from src.utils.logger.logger import logger

# Configuration files mapped to GDRIVE_CONFIG_FOLDER_ID
CONFIG_FILES: list[Path] = [
    DATA_DIR / "portfolio.json",
    DATA_DIR / "portfolio_targets.json",
    DATA_DIR / "etf_cache.json",
]

# Database file mapped dynamically to DEFAULT_DB_PATH to avoid filename mismatch
DB_FILE: Path = Path(DEFAULT_DB_PATH)

app: typer.Typer = typer.Typer(
    name="finances",
    help="CLI tool for monitoring portfolio performance and "
    "investment opportunity evaluation ranking.",
    add_completion=False,
)

app.add_typer(dashboard_app, name="dashboard")
app.add_typer(report_app, name="report")

console: Console = Console()


def _pull_cloud_data() -> bool:
    """Pulls database and configuration files from Drive folders."""
    db_service: GDriveService = GDriveService(
        folder_id=settings.gdrive_database_folder_id
    )
    db_ok: bool = bool(db_service.download_file(DB_FILE.name, DB_FILE))

    config_service: GDriveService = GDriveService(
        folder_id=settings.gdrive_config_folder_id
    )
    results: dict[str, bool] = config_service.sync_files(CONFIG_FILES, direction="pull")
    return db_ok and all(results.values())


def _push_cloud_data() -> bool:
    """Pushes database and config files to respective Drive folders."""
    db_ok: bool = True
    if DB_FILE.exists():
        db_service: GDriveService = GDriveService(
            folder_id=settings.gdrive_database_folder_id
        )
        db_ok = bool(db_service.upload_file(DB_FILE, overwrite=True))

    existing_config: list[Path] = [f for f in CONFIG_FILES if f.exists()]
    config_ok: bool = True
    if existing_config:
        config_service: GDriveService = GDriveService(
            folder_id=settings.gdrive_config_folder_id
        )
        results: dict[str, bool] = config_service.sync_files(
            existing_config, direction="push"
        )
        config_ok = all(results.values())

    return db_ok and config_ok


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    """Validates environment settings on startup."""
    try:
        _ = settings
    except ValidationError as err:
        logger.error(f"Environment configuration validation failed:\n{err}")
        raise typer.Exit(code=1) from err
    except Exception as e:
        logger.error(f"Failed to validate environment configuration: {e}")
        raise typer.Exit(code=1) from e


@app.command(name="save-snapshot")
def save_snapshot_cmd() -> None:
    """Calculates valuation and saves history snapshot to local database."""
    try:
        snapshot_data: PortfolioSnapshot | None = get_snapshot()
        if not snapshot_data:
            logger.error("Failed to calculate portfolio snapshot.")
            raise typer.Exit(code=1)

        save_snapshot(snapshot_data)
    except typer.Exit:
        raise
    except Exception as err:
        logger.error(f"Unexpected error saving snapshot: {err}")
        raise typer.Exit(code=1) from err


@app.command(name="update")
def update_cmd(
    targets_file: Annotated[
        Path,
        typer.Option(
            "--targets-file",
            "-t",
            help="Path to JSON file containing target wishlist.",
        ),
    ] = DATA_DIR
    / "portfolio_targets.json",
    portfolio_file: Annotated[
        Path,
        typer.Option(
            "--portfolio-file",
            "-p",
            help="Path to JSON file containing active holdings.",
        ),
    ] = DATA_DIR
    / "portfolio.json",
    db_path: Annotated[
        Path,
        typer.Option("--db-path", help="Path to SQLite database file."),
    ] = Path(DEFAULT_DB_PATH),
    skip_ai: Annotated[
        bool,
        typer.Option("--skip-ai", help="Skip Gemini AI analysis."),
    ] = False,
    notify: Annotated[
        bool,
        typer.Option("--notify", help="Dispatch results to Discord webhook."),
    ] = False,
) -> None:
    """Fetches prices once, saves snapshot, then scores opportunity — atomically.

    Guarantees that the snapshot and the opportunity matrix share the exact
    same market prices, eliminating any race condition between the two steps.
    """
    logger.section("Atomic Update: Snapshot → Opportunity Scoring")

    snapshot_data: PortfolioSnapshot | None = get_snapshot()
    if not snapshot_data:
        logger.error("Failed to calculate portfolio snapshot. Aborting update.")
        raise typer.Exit(code=1)

    save_snapshot(snapshot_data)

    _run_rebalance(
        targets_file=targets_file,
        portfolio_file=portfolio_file,
        db_path=db_path,
        skip_ai=skip_ai,
        verbose=False,
        notify=notify,
        injected_snapshot=snapshot_data,
    )


@app.command(name="pull-config")
def pull_config_cmd() -> None:
    """Pulls configuration files and database from Google Drive."""
    logger.section("Pulling Configuration from Google Drive")
    try:
        success: bool = _pull_cloud_data()
        if success:
            logger.success("Successfully pulled configuration files from Google Drive.")
        else:
            logger.warning("One or more configuration files failed to download.")
    except Exception as err:
        logger.error(f"Google Drive pull failed: {err}")
        raise typer.Exit(code=1) from err


@app.command(name="push-config")
def push_config_cmd() -> None:
    """Pushes local configuration files and database to Google Drive."""
    logger.section("Pushing Configuration to Google Drive")
    try:
        success: bool = _push_cloud_data()
        if success:
            logger.success("Successfully pushed configuration files to Google Drive.")
        else:
            logger.warning("One or more configuration files failed to upload.")
    except Exception as err:
        logger.error(f"Google Drive push failed: {err}")
        raise typer.Exit(code=1) from err


def _display_single_etf_details(asset: Asset, provider: ETFProvider) -> None:
    """Displays detailed composition and breakdowns for an ETF using Rich Panel."""
    details: ETFDetails | None = provider.get_details(asset)
    if not details:
        console.print(
            f"[red]Failed to fetch details for {asset.name} ({asset.isin}).[/red]"
        )
        return

    mkt: ETFMarketData | None = provider.get_market_data(asset)

    def _fmt_float(val: float | None, suffix: str = "") -> str:
        return f"{val:.2f}{suffix}" if val is not None else "N/A"

    def _fmt_pct(val: float | None) -> str:
        return f"{val:.2f}%" if val is not None else "N/A"

    ter_str: str = f"{details.ter_pct:.2f}%" if details.ter_pct is not None else "N/A"

    card_text: Text = Text()
    card_text.append("Asset Name: ", style="bold white")
    card_text.append(f"{asset.name} ({asset.isin})\n", style="bold yellow")
    card_text.append("Asset Type: ", style="bold blue")
    card_text.append("ETF\n", style="bold blue")
    card_text.append("Yahoo Ticker: ", style="bold white")
    card_text.append(f"{asset.yahoo_ticker}\n", style="bold cyan")
    if asset.xtb_ticker:
        card_text.append("XTB Ticker: ", style="bold white")
        card_text.append(f"{asset.xtb_ticker}\n", style="bold cyan")

    if mkt:
        currency: str = mkt.currency or "EUR"
        nav_currency: str = details.fund_currency or currency
        card_text.append("Price: ", style="bold white")
        card_text.append(f"{_fmt_float(mkt.price)} {currency}\n", style="bold green")
        card_text.append("NAV: ", style="bold white")
        card_text.append(
            f"{_fmt_float(mkt.nav_price)} {nav_currency}\n", style="bold green"
        )
        card_text.append("52W High: ", style="bold white")
        card_text.append(
            f"{_fmt_float(mkt.fifty_two_week_high)} {currency}  ", style="bold green"
        )
        card_text.append("52W Low: ", style="bold white")
        card_text.append(
            f"{_fmt_float(mkt.fifty_two_week_low)} {currency}\n", style="bold green"
        )
        card_text.append("52W Change: ", style="bold white")
        card_text.append(
            f"{_fmt_pct(mkt.fifty_two_week_change_pct)}\n", style="bold green"
        )
        card_text.append("50D Avg: ", style="bold white")
        card_text.append(
            f"{_fmt_float(mkt.fifty_day_average)} {currency}  ", style="bold green"
        )
        card_text.append("200D Avg: ", style="bold white")
        card_text.append(
            f"{_fmt_float(mkt.two_hundred_day_average)} {currency}\n",
            style="bold green",
        )
        card_text.append("Avg Volume: ", style="bold white")
        card_text.append(
            f"{mkt.average_volume:,}\n" if mkt.average_volume else "N/A\n",
            style="bold green",
        )

    card_text.append("TER: ", style="bold white")
    card_text.append(f"{ter_str}\n", style="bold green")
    if details.index_name:
        card_text.append("Index: ", style="bold white")
        card_text.append(f"{details.index_name}\n", style="bold green")
    if details.fund_size_eur_m is not None:
        card_text.append("Fund Size: ", style="bold white")
        card_text.append(f"EUR {details.fund_size_eur_m:,.0f}m\n", style="bold green")
    if details.holdings_count is not None:
        card_text.append("Holdings Count: ", style="bold white")
        card_text.append(f"{details.holdings_count:,}\n", style="bold green")
    if details.replication:
        card_text.append("Replication: ", style="bold white")
        card_text.append(f"{details.replication}\n", style="bold green")
    if details.distribution_policy:
        card_text.append("Distribution: ", style="bold white")
        card_text.append(f"{details.distribution_policy}\n", style="bold green")
    if details.fund_currency:
        card_text.append("Fund Currency: ", style="bold white")
        card_text.append(f"{details.fund_currency}\n", style="bold green")
    if details.inception_date:
        card_text.append("Inception Date: ", style="bold white")
        card_text.append(f"{details.inception_date}\n", style="bold green")
    if details.volatility_1y_pct is not None:
        card_text.append("Volatility 1Y: ", style="bold white")
        card_text.append(f"{details.volatility_1y_pct:.2f}%\n", style="bold green")

    if details.holdings:
        card_text.append("\nTop Holdings:\n", style="bold underline")
        for h in details.holdings:
            if h.weight_pct <= 0:
                continue
            h_isin: str = f" ({h.isin})" if h.isin else ""
            card_text.append("  • ", style="dim")
            card_text.append(f"{h.name}{h_isin}: ", style="bold white")
            card_text.append(f"{h.weight_pct:.2f}%\n")

    if details.sector_breakdown:
        card_text.append("\nSector Breakdown:\n", style="bold underline")
        for s in details.sector_breakdown:
            if s.weight_pct <= 0:
                continue
            card_text.append("  • ", style="dim")
            card_text.append(f"{s.sector_name}: ", style="bold white")
            card_text.append(f"{s.weight_pct:.2f}%\n")

    if details.country_breakdown:
        card_text.append("\nCountry Breakdown:\n", style="bold underline")
        for c in details.country_breakdown:
            if c.weight_pct <= 0:
                continue
            card_text.append("  • ", style="dim")
            card_text.append(f"{c.country_name}: ", style="bold white")
            card_text.append(f"{c.weight_pct:.2f}%\n")

    panel: Panel = Panel(
        card_text,
        title=f"[bold cyan]ETF DETAILS - {asset.yahoo_ticker}[/bold cyan]",
    )
    console.print(panel)


@app.command(name="etf-details")
def etf_details_cmd(
    isin: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional ISIN of the ETF to inspect. "
                "If omitted, inspects all ETFs in portfolio."
            )
        ),
    ] = None,
) -> None:
    """Inspects composition, TER, holdings, and breakdowns for ETFs."""
    provider: ETFProvider = ETFProvider()
    repo: SqlitePortfolioRepository = SqlitePortfolioRepository(DEFAULT_DB_PATH)

    try:
        if isin:
            clean_isin: str = isin.strip().upper()
            if len(clean_isin) != 12:
                logger.error(f"Invalid ISIN format '{isin}'. Expected 12-char code.")
                raise typer.Exit(code=1)

            assets_lookup: list[Asset] = []
            try:
                assets_lookup = repo.load_assets()
            except Exception as e:
                logger.warning(f"Could not load portfolio assets for name lookup: {e}")

            matched_asset: Asset | None = next(
                (a for a in assets_lookup if a.isin and a.isin.upper() == clean_isin),
                None,
            )
            display_asset: Asset = matched_asset or Asset(
                isin=clean_isin,
                name=clean_isin,
                yahoo_ticker=clean_isin,
                quantity=0.0,
                average_buy_price=0.0,
                asset_type="ETF",
            )
            _display_single_etf_details(display_asset, provider)
            return

        try:
            assets: list[Asset] = repo.load_assets()
        except Exception as e:
            logger.error(f"Failed to load portfolio assets: {e}")
            raise typer.Exit(code=1) from e

        etf_assets: list[Asset] = [
            a
            for a in assets
            if str(a.asset_type).upper() == "ETF" and a.isin and len(a.isin) == 12
        ]
        if not etf_assets:
            logger.warning("No active ETF holdings found in portfolio.")
            return

        for asset in etf_assets:
            _display_single_etf_details(asset, provider)
    except typer.Exit:
        raise
    except Exception as err:
        logger.error(f"Unexpected error fetching ETF details: {err}")
        raise typer.Exit(code=1) from err


def _format_market_cap(val: float | None) -> str:
    """Formats market cap values with dynamic scale suffixes (B/T)."""
    if val is None:
        return "N/A"
    if val >= 1_000_000_000_000:
        return f"{val / 1_000_000_000_000:.2f}T"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    return f"{val:.2f}"


def _display_single_stock_details(
    ticker: str, name: str, provider: StockProvider
) -> None:
    """Displays all fundamental and market metrics for a single stock
    using Rich Panel."""
    dummy_asset: Asset = Asset(
        isin=ticker if len(ticker) == 12 else "",
        name=name,
        yahoo_ticker=ticker,
        quantity=0.0,
        average_buy_price=0.0,
        asset_type="STOCK",
    )

    quote: Quotation | None = provider.get_price(dummy_asset)
    details: StockDetails | None = provider.get_details(dummy_asset)

    if not details:
        console.print(
            f"[red]Failed to fetch fundamental metrics for {name} ({ticker}).[/red]"
        )
        return

    # quote.currency is the display currency after FX conversion (always EUR for
    # non-EUR assets). details.currency is the native quote currency from Yahoo
    # (e.g. DKK for NOVO-B.CO). Price/market fields from get_price are in
    # quote_currency; fundamental fields stored in StockDetails are in native_currency.
    quote_currency: str = quote.currency if quote else (details.currency or "")
    native_currency: str = details.currency or quote_currency

    def _fmt(val: float | None, decimals: int = 2, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}{suffix}"

    def _fmt_pct(val: float | None) -> str:
        if val is None:
            return "N/A"
        return f"{val:.2f}%"

    def _fmt_vol(val: int | None) -> str:
        if val is None:
            return "N/A"
        if val >= 1_000_000:
            return f"{val / 1_000_000:.2f}M"
        if val >= 1_000:
            return f"{val / 1_000:.1f}K"
        return str(val)

    card_text: Text = Text()

    # Identity
    card_text.append("Asset Name: ", style="bold white")
    card_text.append(f"{name} ({ticker})\n", style="bold yellow")
    card_text.append("Asset Type: ", style="bold white")
    card_text.append("STOCK\n", style="bold blue")
    card_text.append("Sector: ", style="bold white")
    card_text.append(f"{details.sector or 'N/A'}\n")
    card_text.append("Industry: ", style="bold white")
    card_text.append(f"{details.industry or 'N/A'}\n")
    card_text.append("Country: ", style="bold white")
    card_text.append(f"{details.country or 'N/A'}\n")

    # Price & market data
    card_text.append("\n── Price & Market Data ──\n", style="dim")
    if quote:
        card_text.append("Price: ", style="bold white")
        card_text.append(f"{quote.price:.2f} {quote_currency}\n", style="bold green")
    card_text.append("Market Cap: ", style="bold white")
    card_text.append(f"{_format_market_cap(details.market_cap)}\n", style="yellow")
    card_text.append("52W High: ", style="bold white")
    card_text.append(f"{_fmt(details.fifty_two_week_high)} {native_currency}\n")
    card_text.append("52W Low: ", style="bold white")
    card_text.append(f"{_fmt(details.fifty_two_week_low)} {native_currency}\n")
    card_text.append("52W Change: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.fifty_two_week_change_pct)}\n")
    card_text.append("50D Average: ", style="bold white")
    card_text.append(f"{_fmt(details.fifty_day_average)} {native_currency}\n")
    card_text.append("200D Average: ", style="bold white")
    card_text.append(f"{_fmt(details.two_hundred_day_average)} {native_currency}\n")
    card_text.append("Avg Volume: ", style="bold white")
    card_text.append(f"{_fmt_vol(details.average_volume)}\n")

    # Valuation
    card_text.append("\n── Valuation ──\n", style="dim")
    card_text.append("P/E (Trailing): ", style="bold white")
    card_text.append(f"{_fmt(details.pe_ratio)}\n")
    card_text.append("P/E (Forward): ", style="bold white")
    card_text.append(f"{_fmt(details.forward_pe)}\n")
    card_text.append("PEG Ratio: ", style="bold white")
    card_text.append(f"{_fmt(details.peg_ratio)}\n")
    card_text.append("P/B Ratio: ", style="bold white")
    card_text.append(f"{_fmt(details.price_to_book)}\n")
    card_text.append("EPS (TTM): ", style="bold white")
    card_text.append(f"{_fmt(details.eps_trailing_ttm)} {native_currency}\n")
    card_text.append("EPS (Forward): ", style="bold white")
    card_text.append(f"{_fmt(details.eps_forward)} {native_currency}\n")
    card_text.append("Beta: ", style="bold white")
    card_text.append(f"{_fmt(details.beta)}\n")
    card_text.append("Dividend Yield: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.dividend_yield_pct)}\n", style="green")

    # Profitability & growth
    card_text.append("\n── Profitability & Growth ──\n", style="dim")
    card_text.append("Gross Margin: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.gross_margins_pct)}\n")
    card_text.append("Operating Margin: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.operating_margins_pct)}\n")
    card_text.append("Profit Margin: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.profit_margins_pct)}\n")
    card_text.append("Revenue Growth (YoY): ", style="bold white")
    card_text.append(f"{_fmt_pct(details.revenue_growth_pct)}\n")
    card_text.append("Earnings Growth (YoY): ", style="bold white")
    card_text.append(f"{_fmt_pct(details.earnings_growth_pct)}\n")
    card_text.append("Return on Equity: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.return_on_equity_pct)}\n")
    card_text.append("Return on Assets: ", style="bold white")
    card_text.append(f"{_fmt_pct(details.return_on_assets_pct)}\n")

    # Financial health
    card_text.append("\n── Financial Health ──\n", style="dim")
    card_text.append("Debt/Equity: ", style="bold white")
    card_text.append(f"{_fmt(details.total_debt_to_equity)}\n")
    card_text.append("Free Cash Flow: ", style="bold white")
    fcf_str: str = (
        _format_market_cap(details.free_cashflow) if details.free_cashflow else "N/A"
    )
    card_text.append(f"{fcf_str}\n")
    card_text.append("Short Ratio: ", style="bold white")
    card_text.append(f"{_fmt(details.short_ratio)}\n")

    # Analyst consensus
    card_text.append("\n── Analyst Consensus ──\n", style="dim")
    card_text.append("Recommendation: ", style="bold white")
    rec: str = (details.recommendation_key or "N/A").upper()
    rec_style: str = (
        "bold green" if rec == "BUY" else "bold red" if rec == "SELL" else "yellow"
    )
    card_text.append(f"{rec}\n", style=rec_style)
    card_text.append("Target (Mean): ", style="bold white")
    card_text.append(f"{_fmt(details.target_mean_price)} {native_currency}\n")
    card_text.append("Target (High): ", style="bold white")
    card_text.append(f"{_fmt(details.target_high_price)} {native_currency}\n")
    card_text.append("Target (Low): ", style="bold white")
    card_text.append(f"{_fmt(details.target_low_price)} {native_currency}\n")
    card_text.append("# Analysts: ", style="bold white")
    card_text.append(f"{details.number_of_analyst_opinions or 'N/A'}\n")

    panel: Panel = Panel(
        card_text,
        title=f"[bold cyan]STOCK DETAILS - {ticker}[/bold cyan]",
    )
    console.print(panel)


@app.command(name="analyze-quality")
def analyze_quality_cli(
    ticker: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional ticker symbol or ISIN to analyze. "
                "If omitted, analyzes all active portfolio assets."
            )
        ),
    ] = None,
    notify: Annotated[
        bool,
        typer.Option(
            "--notify",
            help="Dispatch results to Discord webhook if configured.",
        ),
    ] = False,
) -> None:
    """Evaluates absolute quality tiers and metrics for assets."""
    try:
        analyze_quality_cmd(ticker=ticker, notify=notify)
    except typer.Exit:
        raise
    except Exception as err:
        logger.error(f"Failed to analyze asset quality: {err}")
        raise typer.Exit(code=1) from err


@app.command(name="stock-details")
def stock_details_cmd(
    ticker: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional stock ticker symbol or ISIN. "
                "If omitted, inspects all stocks in portfolio."
            )
        ),
    ] = None,
) -> None:
    """Inspects fundamental financial metrics for portfolio stocks."""
    provider: StockProvider = StockProvider()
    repo: SqlitePortfolioRepository = SqlitePortfolioRepository(DEFAULT_DB_PATH)

    try:
        if ticker:
            clean_ticker: str = ticker.strip()
            assets_lookup: list[Asset] = []
            try:
                assets_lookup = repo.load_assets()
            except Exception as e:
                logger.warning(f"Could not load portfolio assets for name lookup: {e}")

            matched_asset: Asset | None = next(
                (
                    a
                    for a in assets_lookup
                    if a.yahoo_ticker.upper() == clean_ticker.upper()
                    or (a.isin and a.isin.upper() == clean_ticker.upper())
                ),
                None,
            )
            asset_name: str = matched_asset.name if matched_asset else clean_ticker
            _display_single_stock_details(clean_ticker, asset_name, provider)
            return

        try:
            assets: list[Asset] = repo.load_assets()
        except Exception as e:
            logger.error(f"Failed to load portfolio assets: {e}")
            raise typer.Exit(code=1) from e

        stock_assets: list[Asset] = [
            a for a in assets if str(a.asset_type).upper() == "STOCK"
        ]

        if not stock_assets:
            logger.warning("No active stock holdings found in portfolio.")
            return

        for asset in stock_assets:
            _display_single_stock_details(asset.yahoo_ticker, asset.name, provider)
    except typer.Exit:
        raise
    except Exception as err:
        logger.error(f"Unexpected error fetching stock details: {err}")
        raise typer.Exit(code=1) from err


@app.command(name="exposure-check")
def check_exposure() -> None:
    """Displays consolidated look-through exposure in terminal."""
    exposure_engine: ExposureEngine = ExposureEngine()
    history_repo: SqliteHistoryRepository = SqliteHistoryRepository(DEFAULT_DB_PATH)
    history: list[PortfolioSnapshot] = history_repo.load_history()

    if not history:
        console.print("[red]No portfolio history found for exposure check.[/red]")
        return

    latest_snapshot: PortfolioSnapshot = history[-1]

    with console.status("[bold cyan]Calculating look-through exposures..."):
        sectors: dict[str, float]
        countries: dict[str, float]
        sectors, countries = exposure_engine.calculate_consolidated_exposure(
            latest_snapshot
        )
        companies: dict[str, float] = exposure_engine.calculate_company_exposure(
            latest_snapshot
        )

        sector_violations: list[str] = exposure_engine.validate_exposure_limits(
            sectors, countries
        )
        company_violations: list[str] = exposure_engine.validate_company_limits(
            companies
        )

    # Generate charts
    generate_exposure_pie_chart(sectors, "Sector Exposure", "exposure_sector.png")
    generate_exposure_pie_chart(countries, "Country Exposure", "exposure_country.png")
    generate_exposure_pie_chart(
        dict(sorted(companies.items(), key=lambda x: x[1], reverse=True)[:10]),
        "Top 10 Company Exposure",
        "exposure_company.png",
    )

    card_text: Text = Text()
    card_text.append("Consolidated Sector Exposure:\n", style="bold underline")
    for sector, pct in sorted(sectors.items(), key=lambda x: x[1], reverse=True):
        is_tech: bool = "technology" in sector.lower() or "tech" in sector.lower()
        sector_limit: float = (
            settings.max_tech_allocation_pct
            if is_tech
            else settings.max_other_sector_allocation_pct
        )
        sector_status_style: str = "bold red" if pct > sector_limit else "green"
        card_text.append("  • ", style="dim")
        card_text.append(f"{sector}: ", style="bold white")
        card_text.append(f"{pct:.2f}% ", style=sector_status_style)
        card_text.append(f"(Max: {sector_limit:.1f}%)\n", style="dim")

    card_text.append("\nConsolidated Country Exposure:\n", style="bold underline")
    for country, pct in sorted(countries.items(), key=lambda x: x[1], reverse=True):
        country_limit: float = settings.max_country_allocation_pct
        country_status_style: str = "bold red" if pct > country_limit else "green"
        card_text.append("  • ", style="dim")
        card_text.append(f"{country}: ", style="bold white")
        card_text.append(f"{pct:.2f}% ", style=country_status_style)
        card_text.append(f"(Max: {country_limit:.1f}%)\n", style="dim")

    card_text.append("\nTop Look-Through Company Exposure:\n", style="bold underline")
    for comp, pct in sorted(companies.items(), key=lambda x: x[1], reverse=True)[:10]:
        comp_limit: float = settings.max_company_allocation_pct
        comp_status_style: str = "bold red" if pct > comp_limit else "green"
        card_text.append("  • ", style="dim")
        card_text.append(f"{comp}: ", style="bold white")
        card_text.append(f"{pct:.2f}%\n", style=comp_status_style)

    card_text.append("\nPolicy Compliance Status:\n", style="bold underline")
    violations: list[str] = sector_violations + company_violations
    if violations:
        card_text.append("  ⚠️ Policy Violations Detected:\n", style="bold red")
        for v in violations:
            card_text.append(f"    - {v}\n", style="red")
    else:
        card_text.append("  ✓ All exposure limits are respected.\n", style="bold green")

    panel: Panel = Panel(
        card_text,
        title="[bold cyan]PORTFOLIO LOOK-THROUGH EXPOSURE ANALYSIS[/bold cyan]",
    )
    console.print(panel)


@app.command(name="opportunity_evaluation")
def opportunity_cmd(
    targets_file: Annotated[
        Path,
        typer.Option(
            "--targets-file",
            "-t",
            help="Path to JSON file containing target wishlist.",
        ),
    ] = DATA_DIR
    / "portfolio_targets.json",
    portfolio_file: Annotated[
        Path,
        typer.Option(
            "--portfolio-file",
            "-p",
            help="Path to JSON file containing active holdings.",
        ),
    ] = DATA_DIR
    / "portfolio.json",
    db_path: Annotated[
        Path,
        typer.Option(
            "--db-path",
            help="Path to SQLite database file.",
        ),
    ] = DEFAULT_DB_PATH,
    skip_ai: Annotated[
        bool,
        typer.Option(
            "--skip-ai",
            help="Skip Gemini AI analysis and display quant scores only.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Display detailed score factors breakdown.",
        ),
    ] = False,
    notify: Annotated[
        bool,
        typer.Option(
            "--notify",
            help="Dispatch results to Discord webhook if configured.",
        ),
    ] = False,
) -> None:
    """Ranks targets and provides AI-driven recommendations."""
    recommend_rebalance(
        targets_file=targets_file,
        portfolio_file=portfolio_file,
        db_path=db_path,
        skip_ai=skip_ai,
        verbose=verbose,
        notify=notify,
    )


@app.command(name="sync-fundamentals")
def sync_fundamentals_cmd(
    db_path: Annotated[
        Path,
        typer.Option(
            "--db-path",
            help="Path to SQLite database file.",
        ),
    ] = DEFAULT_DB_PATH,
) -> None:
    """Synchronizes portfolio fundamentals into local SQLite database."""
    try:
        sync_portfolio_fundamentals(db_path=db_path)
    except Exception as err:
        logger.error(f"Failed to synchronize portfolio fundamentals: {err}")
        raise typer.Exit(code=1) from err


@app.command(name="project-growth")
def project_growth_cmd(
    initial_value: Annotated[
        float | None,
        typer.Option("--initial-value", "-i", help="Initial portfolio capital."),
    ] = None,
    monthly_contribution: Annotated[
        float,
        typer.Option(
            "--monthly-contribution", "-m", help="Regular monthly contribution in EUR."
        ),
    ] = 0.0,
    expected_return: Annotated[
        float,
        typer.Option(
            "--expected-return", "-r", help="Custom expected annual return percentage."
        ),
    ] = 0.07,
    compare_scenarios: Annotated[
        bool,
        typer.Option(
            "--compare-scenarios",
            "-c",
            help="Display comparison across conservative, "
            "moderate, and aggressive scenarios.",
        ),
    ] = False,
    db_path: Annotated[
        Path,
        typer.Option("--db-path", help="Path to SQLite database file."),
    ] = DEFAULT_DB_PATH,
) -> None:
    """Projects portfolio growth over 10, 20, and 30-year horizons."""
    from src.infra.database.finance_sql_extraction import FinanceSQLExtractor

    engine = ProjectionEngine()
    presenter = ProjectionPresenter()
    extractor = FinanceSQLExtractor(db_path=db_path)

    # Determine initial value
    if initial_value is None:
        history = extractor.fetch_portfolio_history()
        initial_value = history[-1].total_value_eur if history else 0.0

    # Determine CAGR for primary scenario
    hist_cagr = engine.calculate_historical_cagr(extractor)

    # Define scenarios
    scenarios = []
    if compare_scenarios:
        for name, rate in [
            ("Conservative - 5%", 0.05),
            ("Moderate - 7%", 0.07),
            ("Aggressive - 9%", 0.09),
        ]:
            scenarios.append(
                engine.generate_scenario(
                    name, initial_value, monthly_contribution, rate
                )
            )
    else:
        scenarios.append(
            engine.generate_scenario(
                "Primary",
                initial_value,
                monthly_contribution,
                expected_return or hist_cagr,
            )
        )

    result = GrowthProjectionResult(
        initial_value=initial_value,
        monthly_contribution=monthly_contribution,
        scenarios=scenarios,
        historical_cagr_pct=hist_cagr,
        primary_scenario=scenarios[0],
    )

    presenter.render_summary(result)
    for scenario in scenarios:
        presenter.render_milestones(result, scenario_name=scenario.name)


if __name__ == "__main__":
    app()
