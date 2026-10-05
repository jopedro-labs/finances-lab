"""CLI module for evaluating investment targets and opportunity
ranking with exposure policy constraints."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config import DATA_DIR, OUTPUT_DIR, settings
from src.core.exceptions import (
    GeminiAPIError,
    GeminiAuthError,
    GeminiQuotaError,
)
from src.core.models import (
    Asset,
    ETFDetails,
    PortfolioSnapshot,
    Quotation,
    RebalanceRecommendation,
    RecommendationAction,
    StockDetails,
)
from src.core.opportunity_evaluation.base import AssetScore
from src.core.opportunity_evaluation.engine import PortfolioOpportunityEngine
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import SqliteHistoryRepository, SqliteOpportunityRepository
from src.infra.ai.client import GeminiClient
from src.infra.database.connection import DEFAULT_DB_PATH
from src.infra.notifications.discord import send_discord_notification
from src.utils.logger.logger import logger

app: typer.Typer = typer.Typer(
    help="Investment opportunity evaluation engine CLI commands."
)
console: Console = Console()


def load_json_data(file_path: Path) -> list[dict[str, Any]]:
    """Loads and normalizes JSON data containing asset lists or holdings."""
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return []

    try:
        with open(file_path, encoding="utf-8") as file:
            data: Any = json.load(file)
    except Exception as err:
        logger.error(f"Failed to read JSON file '{file_path}': {err}")
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and "assets" in data:
        raw_assets: Any = data.get("assets")
        if isinstance(raw_assets, list):
            return [item for item in raw_assets if isinstance(item, dict)]

    return []


def calculate_current_allocations(
    portfolio_items: list[dict[str, Any]],
    stock_provider: StockProvider,
) -> tuple[dict[str, float], float]:
    """Fetches live prices for active holdings and computes real allocation %."""
    holdings_value_map: dict[str, float] = {}
    total_portfolio_value: float = 0.0

    for item in portfolio_items:
        symbol: str = str(item.get("yahoo_ticker") or item.get("symbol") or "").strip()
        quantity: float = float(item.get("quantity", 0.0))

        if not symbol or quantity <= 0.0:
            continue

        asset_type_val: str = str(
            item.get("asset_type") or item.get("type") or "STOCK"
        ).upper()

        dummy_asset: Asset = Asset(
            name=symbol,
            isin=str(item.get("isin", "")),
            yahoo_ticker=symbol,
            quantity=quantity,
            average_buy_price=float(
                item.get("averageBuyPrice", item.get("average_buy_price", 0.0))
            ),
            asset_type=asset_type_val,
        )

        quote: Quotation | None = stock_provider.get_price(dummy_asset)
        current_price: float = quote.price if quote else 0.0

        if current_price <= 0.0:
            logger.warning(
                f"Could not retrieve valid price for holding '{symbol}'. "
                "Skipping position value calculation."
            )
            continue

        position_value: float = quantity * current_price
        holdings_value_map[symbol] = position_value
        total_portfolio_value += position_value

    if total_portfolio_value <= 0.0:
        return {}, 0.0

    allocation_pct_map: dict[str, float] = {
        symbol: (val / total_portfolio_value) * 100.0
        for symbol, val in holdings_value_map.items()
    }

    return allocation_pct_map, total_portfolio_value


def enrich_target_asset(
    target: dict[str, Any],
    current_alloc_pct: float,
    stock_provider: StockProvider,
    etf_provider: ETFProvider,
) -> dict[str, Any]:
    """Enriches wishlist asset with real-time market data, TER, and breakdowns."""
    symbol: str = str(target.get("yahoo_ticker") or target.get("symbol") or "").strip()
    asset_type: str = str(target.get("asset_type") or target.get("type") or "").upper()
    isin: str = str(target.get("isin", ""))

    if not symbol or not asset_type:
        raise ValueError(f"Missing symbol or type for target asset: {target}")

    dummy_asset: Asset = Asset(
        name=symbol,
        isin=isin,
        yahoo_ticker=symbol,
        quantity=0.0,
        average_buy_price=0.0,
        asset_type=asset_type,
    )

    quote: Quotation | None = stock_provider.get_price(dummy_asset)
    current_price: float = quote.price if quote else 0.0

    if current_price <= 0.0:
        logger.warning(f"Live market price unavailable for target '{symbol}'.")

    stock_details: StockDetails | None = stock_provider.get_details(dummy_asset)

    peak_price: float = (
        stock_details.fifty_two_week_high
        if stock_details and stock_details.fifty_two_week_high
        else current_price
    )
    if peak_price <= 0.0:
        peak_price = max(current_price, 0.01)

    low_52w: float | None = stock_details.fifty_two_week_low if stock_details else None

    ter: float | None = None
    sector_breakdown: list[dict[str, Any]] = []
    country_breakdown: list[dict[str, Any]] = []
    top_holdings: list[dict[str, Any]] = []

    if asset_type == "ETF":
        etf_details: ETFDetails | None = etf_provider.get_details(dummy_asset)
        if etf_details:
            ter = etf_details.ter_pct
            sector_breakdown = [s.to_dict() for s in etf_details.sector_breakdown]
            country_breakdown = [c.to_dict() for c in etf_details.country_breakdown]
            top_holdings = [h.to_dict() for h in etf_details.holdings]

    target_alloc_pct: float = float(target.get("target_allocation_pct", 0.0))
    alloc_gap_pct: float = round(target_alloc_pct - current_alloc_pct, 2)

    country_val: str | None = (
        getattr(stock_details, "country", None)
        if stock_details
        else target.get("country")
    )
    if not country_val and asset_type == "STOCK":
        country_val = "United States"

    price_to_book_val: float | None = (
        stock_details.price_to_book if stock_details else None
    )
    if price_to_book_val is not None and price_to_book_val <= 0:
        price_to_book_val = None

    return {
        "symbol": symbol,
        "isin": isin,
        "asset_type": asset_type,
        "current_price": current_price,
        "peak_price": peak_price,
        "low_52w": low_52w,
        "high_52w": peak_price,
        "target_allocation_pct": target_alloc_pct,
        "current_allocation_pct": current_alloc_pct,
        "allocation_gap_pct": alloc_gap_pct,
        "sector": stock_details.sector if stock_details else target.get("sector"),
        "country": country_val,
        "industry": stock_details.industry if stock_details else None,
        "market_cap": stock_details.market_cap if stock_details else None,
        "trailing_pe": stock_details.pe_ratio if stock_details else None,
        "forward_pe": stock_details.forward_pe if stock_details else None,
        "peg_ratio": stock_details.peg_ratio if stock_details else None,
        "price_to_book": price_to_book_val,
        "dividend_yield_pct": (
            stock_details.dividend_yield_pct if stock_details else None
        ),
        "beta": stock_details.beta if stock_details else None,
        "profit_margins_pct": (
            stock_details.profit_margins_pct if stock_details else None
        ),
        "revenue_growth_pct": (
            stock_details.revenue_growth_pct if stock_details else None
        ),
        "earnings_growth_pct": (
            stock_details.earnings_growth_pct if stock_details else None
        ),
        "total_debt_to_equity": (
            stock_details.total_debt_to_equity if stock_details else None
        ),
        "target_mean_price": (
            stock_details.target_mean_price if stock_details else None
        ),
        "recommendation_key": (
            stock_details.recommendation_key if stock_details else None
        ),
        "ter": ter,
        "sector_breakdown": sector_breakdown,
        "country_breakdown": country_breakdown,
        "top_holdings": top_holdings,
    }


def export_outputs(
    ranked_scores: list[AssetScore],
    asset_dict_map: dict[str, dict[str, Any]],
    recommendations_map: dict[str, RebalanceRecommendation],
    total_val: float,
    has_ai: bool,
    output_dir: Path = OUTPUT_DIR,
) -> list[dict[str, Any]]:
    """Exports CSV matrix and HTML report ordered by rank
    including all recommendation cards."""
    formatted_date_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path: Path = output_dir / "tables/opportunity_output.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    csv_fieldnames: list[str] = [
        "rank",
        "symbol",
        "asset_type",
        "price_eur",
        "current_allocation_pct",
        "target_allocation_pct",
        "dip_score",
        "cost_score",
        "gap_score",
        "quant_score",
        "ai_action",
        "ai_urgency",
        "ai_confidence_pct",
    ]

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer: csv.DictWriter[str] = csv.DictWriter(
                csv_file, fieldnames=csv_fieldnames
            )
            writer.writeheader()

            for rank, score in enumerate(ranked_scores, start=1):
                target_item: dict[str, Any] = asset_dict_map[score.symbol]
                rec: RebalanceRecommendation | None = recommendations_map.get(
                    score.symbol
                )

                row: dict[str, Any] = {
                    "rank": rank,
                    "symbol": score.symbol,
                    "asset_type": score.asset_type.value.upper(),
                    "price_eur": float(target_item["current_price"]),
                    "current_allocation_pct": float(
                        target_item["current_allocation_pct"]
                    ),
                    "target_allocation_pct": float(
                        target_item["target_allocation_pct"]
                    ),
                    "dip_score": score.dip_score,
                    "cost_score": score.cost_score,
                    "gap_score": score.allocation_score,
                    "quant_score": score.total_score,
                    "ai_action": (rec.action.value if rec and rec.action else "N/A"),
                    "ai_urgency": (
                        rec.urgency_level.value if rec and rec.urgency_level else "N/A"
                    ),
                    "ai_confidence_pct": (
                        round(rec.confidence_score * 100, 2) if rec else "N/A"
                    ),
                }
                writer.writerow(row)

        logger.success(f"Successfully exported opportunity matrix CSV to '{csv_path}'.")
    except Exception as err:
        logger.error(f"Failed to export CSV to '{csv_path}': {err}")

    try:
        from src.utils.render import render_html

        assets_ctx: list[dict[str, Any]] = []
        for rank, score in enumerate(ranked_scores, start=1):
            t: dict[str, Any] = asset_dict_map[score.symbol]
            ctx_rec: RebalanceRecommendation | None = recommendations_map.get(
                score.symbol
            )
            assets_ctx.append(
                {
                    "rank": rank,
                    "symbol": score.symbol,
                    "asset_type": score.asset_type.value.upper(),
                    "price_eur": float(t.get("current_price", 0.0)),
                    "current_pct": float(t.get("current_allocation_pct", 0.0)),
                    "target_pct": float(t.get("target_allocation_pct", 0.0)),
                    "score": float(score.total_score),
                    "ai_action": (
                        ctx_rec.action.value if ctx_rec and ctx_rec.action else None
                    ),
                    "ai_urgency": (
                        ctx_rec.urgency_level.value
                        if ctx_rec and ctx_rec.urgency_level
                        else None
                    ),
                    "ai_conf": (
                        f"{ctx_rec.confidence_score * 100:.0f}%" if ctx_rec else None
                    ),
                }
            )

        def _f(v: Any, fmt: str = ".1f") -> str:
            return format(v, fmt) if v is not None and v != 0.0 else "N/A"

        advisories_ctx: list[dict[str, Any]] = []
        if has_ai and recommendations_map:
            score_map_ctx: dict[str, AssetScore] = {s.symbol: s for s in ranked_scores}
            for score in ranked_scores:
                symbol: str = score.symbol
                adv_rec: RebalanceRecommendation | None = recommendations_map.get(
                    symbol
                )
                if not adv_rec or not adv_rec.action:
                    continue

                t = asset_dict_map[symbol]
                si: AssetScore | None = score_map_ctx.get(symbol)
                curr_alloc: float = round(
                    float(t.get("current_allocation_pct", 0.0)), 1
                )
                targ_alloc: float = round(float(t.get("target_allocation_pct", 0.0)), 1)
                adv: dict[str, Any] = {
                    "symbol": symbol,
                    "asset_type": str(t.get("asset_type", "STOCK")).upper(),
                    "action": adv_rec.action.value,
                    "urgency": (
                        adv_rec.urgency_level.value if adv_rec.urgency_level else "N/A"
                    ),
                    "confidence": f"{adv_rec.confidence_score * 100:.0f}%",
                    "price": float(t.get("current_price", 0.0)),
                    "peak": float(t.get("peak_price", 0.0)),
                    "curr_alloc": curr_alloc,
                    "targ_alloc": targ_alloc,
                    "delta": round(targ_alloc - curr_alloc, 1),
                    "dip_score": si.dip_score if si else 0.0,
                    "cost_score": si.cost_score if si else 0.0,
                    "gap_score": si.allocation_score if si else 0.0,
                    "total_score": si.total_score if si else 0.0,
                    "reasoning": adv_rec.reasoning,
                }
                if adv["asset_type"] == "ETF":
                    ter_v: float | None = t.get("ter")
                    hl: list[dict[str, Any]] = t.get("top_holdings", [])
                    sc: list[dict[str, Any]] = t.get("sector_breakdown", [])
                    co: list[dict[str, Any]] = t.get("country_breakdown", [])
                    adv.update(
                        {
                            "ter_str": f"{ter_v:.2f}%" if ter_v is not None else "N/A",
                            "holdings_str": ", ".join(
                                f"{h.get('name','')}"
                                f" ({float(h.get('weight_pct', 0)):.1f}%)"
                                for h in hl[:5]
                            )
                            or "N/A",
                            "sectors_str": ", ".join(
                                f"{s.get('sector_name') or s.get('name', '')}"
                                f" ({float(s.get('weight_pct', 0)):.1f}%)"
                                for s in sc[:4]
                            )
                            or "N/A",
                            "countries_str": ", ".join(
                                f"{c.get('country_name') or c.get('name', '')}"
                                f" ({float(c.get('weight_pct', 0)):.1f}%)"
                                for c in co[:4]
                            )
                            or "N/A",
                        }
                    )
                else:
                    adv.update(
                        {
                            "tr_pe": _f(t.get("trailing_pe")),
                            "fwd_pe": _f(t.get("forward_pe")),
                            "peg": _f(t.get("peg_ratio"), ".2f"),
                            "pb": _f(t.get("price_to_book"), ".2f"),
                            "div_yield": (
                                f"{t['dividend_yield_pct']:.2f}%"
                                if t.get("dividend_yield_pct")
                                else "N/A"
                            ),
                            "beta": _f(t.get("beta"), ".2f"),
                            "margin": (
                                f"{t['profit_margins_pct']:.1f}%"
                                if t.get("profit_margins_pct")
                                else "N/A"
                            ),
                            "rev_growth": (
                                f"{t['revenue_growth_pct']:.1f}%"
                                if t.get("revenue_growth_pct")
                                else "N/A"
                            ),
                            "earn_growth": (
                                f"{t['earnings_growth_pct']:.1f}%"
                                if t.get("earnings_growth_pct")
                                else "N/A"
                            ),
                            "debt_eq": _f(t.get("total_debt_to_equity")),
                        }
                    )
                advisories_ctx.append(adv)

        html_ctx: dict[str, Any] = {
            "generated_at": formatted_date_str,
            "total_value_eur": total_val,
            "assets": assets_ctx,
            "has_ai": has_ai,
            "advisories": advisories_ctx,
            "w_stock_dip": settings.stock_weight_dip,
            "w_stock_pe": settings.stock_weight_forward_pe,
            "w_stock_52w": settings.stock_weight_52w_range,
            "w_stock_gap": settings.stock_weight_allocation,
            "w_etf_dip": settings.etf_weight_dip,
            "w_etf_ter": settings.etf_weight_ter,
            "w_etf_gap": settings.etf_weight_allocation,
            "w_sector_pen": settings.exposure_sector_penalty_weight,
            "w_country_pen": settings.exposure_country_penalty_weight,
        }

        report_path: Path = output_dir / "reports/opportunity_report.html"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        render_html(
            "opportunity_report.html.j2",
            html_ctx,
            report_path,
        )
        logger.success("Successfully exported opportunity report HTML.")
        return advisories_ctx
    except Exception as err:
        logger.error(f"Failed to export opportunity report HTML: {err}")
        return []


def _format_action(action: RecommendationAction | None) -> Text:
    if action == RecommendationAction.BUY:
        return Text("BUY", style="bold green")
    if action == RecommendationAction.SELL:
        return Text("SELL", style="bold red")
    return Text(action.value.upper() if action else "N/A", style="bold yellow")


def _format_urgency(urgency: Any) -> Text:
    val: str = urgency.value.upper() if urgency else "N/A"
    if val == "HIGH":
        return Text(val, style="bold red")
    if val == "MEDIUM":
        return Text(val, style="yellow")
    return Text(val, style="dim")


def _display_rebalance_results(
    ranked_scores: list[AssetScore],
    asset_dict_map: dict[str, dict[str, Any]],
    recommendations_map: dict[str, RebalanceRecommendation],
    total_val: float,
    has_ai: bool,
    verbose: bool = False,
) -> None:
    """Renders opportunity strategy coefficients, matrix, and expanded
    action cards ordered by rank."""
    console.print()

    stock_weights: str = (
        f"Dip: [white]{settings.stock_weight_dip:.2f}[/white] | "
        f"Fwd P/E: [white]{settings.stock_weight_forward_pe:.2f}[/white] | "
        f"52w Range: [white]{settings.stock_weight_52w_range:.2f}[/white] | "
        f"Gap: [white]{settings.stock_weight_allocation:.2f}[/white]"
    )
    etf_weights: str = (
        f"Dip: [white]{settings.etf_weight_dip:.2f}[/white] | "
        f"TER/Cost: [white]{settings.etf_weight_ter:.2f}[/white] | "
        f"Gap: [white]{settings.etf_weight_allocation:.2f}[/white]"
    )
    sec_pen: float = settings.exposure_sector_penalty_weight
    cnt_pen: float = settings.exposure_country_penalty_weight
    penalty_weights: str = (
        f"Sector Penalty: [white]{sec_pen:.2f}[/white] | "
        f"Country Penalty: [white]{cnt_pen:.2f}[/white]"
    )

    summary_text: str = (
        f"[bold]Total Portfolio Value:[/bold] "
        f"[green]{total_val:,.2f} EUR[/green]  │  "
        f"[bold]Target Assets Evaluated:[/bold] "
        f"{len(ranked_scores)}\n\n"
        f"[bold yellow]Active Strategy Weights:[/bold yellow]\n"
        f"  • [bold]Stocks Formula:[/bold] {stock_weights}\n"
        f"  • [bold]ETFs Formula:[/bold]   {etf_weights}\n"
        f"  • [bold]Exposure Penalties:[/bold] {penalty_weights}"
    )

    summary_panel: Panel = Panel(
        summary_text,
        title="[bold cyan]PORTFOLIO & STRATEGY SUMMARY[/bold cyan]",
        expand=True,
    )
    console.print(summary_panel, soft_wrap=True)
    console.print()

    table: Table = Table(
        title="[bold cyan]PORTFOLIO REBALANCING & OPPORTUNITY MATRIX[/bold cyan]",
        header_style="bold",
        show_header=True,
        pad_edge=True,
        expand=False,
    )

    table.add_column(
        "Rank", justify="center", style="yellow", no_wrap=True, min_width=4
    )
    table.add_column(
        "Symbol",
        justify="center",
        style="bold white",
        no_wrap=True,
        min_width=10,
    )
    table.add_column("Type", justify="center", style="dim", no_wrap=True, min_width=6)
    table.add_column("Price (€)", justify="right", no_wrap=True, min_width=9)
    table.add_column("Current %", justify="right", no_wrap=True, min_width=9)
    table.add_column("Target %", justify="right", no_wrap=True, min_width=8)

    if verbose:
        table.add_column(
            "Dip Sc", justify="right", style="dim", no_wrap=True, min_width=6
        )
        table.add_column(
            "Cost Sc", justify="right", style="dim", no_wrap=True, min_width=7
        )
        table.add_column(
            "Gap Sc", justify="right", style="dim", no_wrap=True, min_width=6
        )

    table.add_column(
        "Score", justify="right", style="bold blue", no_wrap=True, min_width=5
    )

    if has_ai:
        table.add_column("AI Action", justify="center", no_wrap=True, min_width=9)
        table.add_column("Urgency", justify="center", no_wrap=True, min_width=7)
        table.add_column("Conf.", justify="right", no_wrap=True, min_width=6)

    for rank, score in enumerate(ranked_scores, start=1):
        target_item: dict[str, Any] = asset_dict_map[score.symbol]
        price: float = float(target_item["current_price"])
        curr_pct: float = float(target_item["current_allocation_pct"])
        targ_pct: float = float(target_item["target_allocation_pct"])

        row_data: list[Any] = [
            str(rank),
            score.symbol,
            score.asset_type.value.upper(),
            f"{price:,.2f}",
            f"{curr_pct:.1f}%",
            f"{targ_pct:.1f}%",
        ]

        if verbose:
            row_data.extend(
                [
                    f"{score.dip_score:.2f}",
                    f"{score.cost_score:.2f}",
                    f"{score.allocation_score:.2f}",
                ]
            )

        row_data.append(f"{score.total_score:.3f}")

        if has_ai:
            rec: RebalanceRecommendation | None = recommendations_map.get(score.symbol)
            if rec:
                table_conf_str: str = f"{rec.confidence_score * 100:.0f}%"
                row_data.extend(
                    [
                        _format_action(rec.action),
                        _format_urgency(rec.urgency_level),
                        table_conf_str,
                    ]
                )
            else:
                row_data.extend(
                    [
                        Text("ERROR", style="bold red"),
                        Text("N/A", style="dim"),
                        "N/A",
                    ]
                )

        table.add_row(*row_data)

    console.print(table, soft_wrap=True)
    console.print()

    score_map: dict[str, AssetScore] = {s.symbol: s for s in ranked_scores}
    if has_ai and recommendations_map:
        console.print("[bold cyan]ACTIONABLE AI ADVISORY INSIGHTS[/bold cyan]")
        for score in ranked_scores:
            symbol: str = score.symbol
            rec = recommendations_map.get(symbol)
            if not rec or not rec.action:
                continue

            target_item = asset_dict_map[symbol]
            act_text: Text = _format_action(rec.action)
            urg_text: Text = _format_urgency(rec.urgency_level)
            confidence_val_str: str = f"{rec.confidence_score * 100:.0f}%"

            curr_price: float = float(target_item.get("current_price", 0.0))
            peak_price: float = float(target_item.get("peak_price", 0.0))
            low_52w: float | None = target_item.get("low_52w")

            curr_alloc: float = float(target_item.get("current_allocation_pct", 0.0))
            targ_alloc: float = float(target_item.get("target_allocation_pct", 0.0))

            delta_pct: float = targ_alloc - curr_alloc
            delta_str: str = (
                f"+{delta_pct:.1f}%" if delta_pct >= 0 else f"{delta_pct:.1f}%"
            )

            val_lines: str = ""
            if target_item.get("asset_type") == "ETF":
                ter_val: float | None = target_item.get("ter")
                ter_str: str = f"{ter_val:.2f}%" if ter_val is not None else "N/A"

                holdings_list: list[dict[str, Any]] = target_item.get(
                    "top_holdings", []
                )
                holdings_str: str = (
                    ", ".join(
                        [
                            f"{h.get('name', '')} "
                            f"({float(h.get('weight_pct', 0)):.1f}%)"
                            for h in holdings_list[:5]
                        ]
                    )
                    if holdings_list
                    else "N/A"
                )

                sectors_list: list[dict[str, Any]] = target_item.get(
                    "sector_breakdown", []
                )
                sectors_str: str = (
                    ", ".join(
                        [
                            f"{s.get('sector_name') or s.get('name', '')} "
                            f"({float(s.get('weight_pct', 0.0)):.1f}%)"
                            for s in sectors_list[:4]
                        ]
                    )
                    if sectors_list
                    else "N/A"
                )

                countries_list: list[dict[str, Any]] = target_item.get(
                    "country_breakdown", []
                )
                countries_str: str = (
                    ", ".join(
                        [
                            f"{c.get('country_name') or c.get('name', '')} "
                            f"({float(c.get('weight_pct', 0.0)):.1f}%)"
                            for c in countries_list[:4]
                        ]
                    )
                    if countries_list
                    else "N/A"
                )

                val_lines = (
                    f"• [bold]Valuation & ETF Metrics:[/bold]\n"
                    f"  - Total Expense Ratio (TER): [cyan]{ter_str}[/cyan]\n"
                    f"  - Top Holdings: [cyan]{holdings_str}[/cyan]\n"
                    f"  - Sector Breakdown: [cyan]{sectors_str}[/cyan]\n"
                    f"  - Country Breakdown: [cyan]{countries_str}[/cyan]"
                )
            else:
                tr_pe: float | None = target_item.get("trailing_pe")
                fw_pe: float | None = target_item.get("forward_pe")
                peg: float | None = target_item.get("peg_ratio")
                pb: float | None = target_item.get("price_to_book")
                div_yield: float | None = target_item.get("dividend_yield_pct")
                beta: float | None = target_item.get("beta")
                margin: float | None = target_item.get("profit_margins_pct")
                rev_growth: float | None = target_item.get("revenue_growth_pct")
                earn_growth: float | None = target_item.get("earnings_growth_pct")
                debt_eq: float | None = target_item.get("total_debt_to_equity")

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
                peak_str: str = f"{peak_price:,.2f} EUR" if peak_price else "N/A"
                val_lines = (
                    f"• [bold]Valuation & Fundamental Metrics:[/bold]\n"
                    f"  - Trailing P/E: [cyan]{tr_str}[/cyan] | "
                    f"Forward P/E: [cyan]{fw_str}[/cyan] | "
                    f"PEG: [cyan]{peg_str}[/cyan] | P/B: [cyan]{pb_str}[/cyan]\n"
                    f"  - Div Yield: [cyan]{div_str}[/cyan] | "
                    f"Beta: [cyan]{beta_str}[/cyan] | "
                    f"Profit Margin: [cyan]{margin_str}[/cyan]\n"
                    f"  - Rev Growth: [cyan]{rev_str}[/cyan] | "
                    f"Earn Growth: [cyan]{earn_str}[/cyan] | "
                    f"Debt/Equity: [cyan]{debt_str}[/cyan]\n"
                    f"  - 52w Range (Low / High): [cyan]{low_str}[/cyan] / "
                    f"[cyan]{peak_str}[/cyan]"
                )

            score_info: AssetScore | None = score_map.get(symbol)
            factor_lines: str = ""
            if score_info:
                cost_sc_str: str = f"{score_info.cost_score:.2f}"
                tot_sc_str: str = f"{score_info.total_score:.3f}"
                factor_lines = (
                    f"• [bold]Factor Scores:[/bold]\n"
                    f"  - Dip Score: "
                    f"[cyan]{score_info.dip_score:.2f}[/cyan]\n"
                    f"  - Valuation/Cost Score: "
                    f"[cyan]{cost_sc_str}[/cyan]\n"
                    f"  - Gap Score: "
                    f"[cyan]{score_info.allocation_score:.2f}[/cyan]\n"
                    f"  - Quant Total: "
                    f"[bold blue]{tot_sc_str}[/bold blue]"
                )

            divider: str = "─" * 67
            panel_content: str = (
                f"[bold]Action:[/bold] {act_text.markup}  │  "
                f"[bold]Urgency:[/bold] {urg_text.markup}  │  "
                f"[bold]Confidence:[/bold] {confidence_val_str}\n"
                f"{divider}\n"
                f"• [bold]Price:[/bold] {curr_price:,.2f} EUR "
                f"(52w Peak: {peak_price:,.2f} EUR)\n"
                f"• [bold]Allocation Gap:[/bold] Current {curr_alloc:.1f}% "
                f"vs Target {targ_alloc:.1f}% "
                f"(Δ Target: [yellow]{delta_str}[/yellow])\n"
                f"{val_lines}\n"
                f"{factor_lines}\n"
                f"{divider}\n"
                f"[italic]{rec.reasoning}[/italic]"
            )

            border_style: str = (
                "green"
                if rec.action == RecommendationAction.BUY
                else "red" if rec.action == RecommendationAction.SELL else "yellow"
            )
            card: Panel = Panel(
                panel_content,
                title=f"[bold cyan]🔹 {symbol}[/bold cyan]",
                border_style=border_style,
                expand=False,
            )
            console.print(card)
        console.print()


@app.command(name="rebalance")
def recommend_rebalance(
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
            help="Skip Gemini AI analysis and display quantitative scores only.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Display detailed quantitative score factors breakdown.",
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
    """Ranks targets and provides AI-driven rebalancing recommendations."""
    targets_raw: list[dict[str, Any]] = load_json_data(targets_file)
    portfolio_raw: list[dict[str, Any]] = load_json_data(portfolio_file)

    if not targets_raw:
        logger.error(f"No targets found in '{targets_file}'.")
        raise typer.Exit(code=1)

    target_sum: float = sum(
        float(t.get("target_allocation_pct", 0.0)) for t in targets_raw
    )
    if abs(target_sum - 100.0) > 0.5:
        logger.warning(
            f"Target allocations sum to {target_sum:.1f}% (expected 100.0%). "
            "Gap scoring and rebalancing signals may be distorted. "
            "Update portfolio_targets.json so all targets sum to 100%."
        )

    stock_provider: StockProvider = StockProvider()
    etf_provider: ETFProvider = ETFProvider()
    opportunity_repo: SqliteOpportunityRepository = SqliteOpportunityRepository(db_path)
    history_repo: SqliteHistoryRepository = SqliteHistoryRepository(db_path)

    with console.status("[bold cyan]Fetching market data and evaluating portfolio..."):
        current_alloc_map: dict[str, float]
        total_val: float
        current_alloc_map, total_val = calculate_current_allocations(
            portfolio_raw, stock_provider
        )

        enriched_assets: list[dict[str, Any]] = []
        for target in targets_raw:
            symbol: str = str(
                target.get("yahoo_ticker") or target.get("symbol") or ""
            ).strip()
            alloc_pct: float = current_alloc_map.get(symbol, 0.0)
            try:
                enriched: dict[str, Any] = enrich_target_asset(
                    target, alloc_pct, stock_provider, etf_provider
                )
                historical_trend: list[dict[str, Any]] = (
                    opportunity_repo.load_asset_history(symbol, limit=3)
                )
                enriched["historical_trend"] = historical_trend

                enriched_assets.append(enriched)
            except Exception as err:
                logger.error(f"Failed to enrich asset '{symbol}': {err}")

    if not enriched_assets:
        logger.error("Could not enrich any target asset.")
        raise typer.Exit(code=1)

    history: list[PortfolioSnapshot] = history_repo.load_history()
    latest_snapshot: PortfolioSnapshot | None = history[-1] if history else None

    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()
    ranked_scores: list[AssetScore] = engine.rank_assets(
        enriched_assets, portfolio_snapshot=latest_snapshot
    )

    gemini_client: GeminiClient | None = None
    if not skip_ai:
        try:
            gemini_client = GeminiClient()
        except GeminiAuthError as err:
            logger.warning(
                f"Gemini AI disabled ({err}). Running in quantitative-only mode."
            )

    recommendations_map: dict[str, RebalanceRecommendation] = {}
    asset_dict_map: dict[str, dict[str, Any]] = {
        str(a["symbol"]): a for a in enriched_assets
    }

    if gemini_client:
        with console.status(
            "[bold magenta]Running Gemini AI batch rebalancing analysis..."
        ):
            portfolio_ctx: dict[str, Any] = {
                "total_portfolio_value_eur": total_val,
            }
            try:
                recommendations_map = gemini_client.analyze_portfolio_batch(
                    assets_data=enriched_assets,
                    portfolio_context=portfolio_ctx,
                )
            except (GeminiAPIError, GeminiQuotaError, Exception) as err:
                logger.error(f"Gemini AI batch analysis failed: {err}")
                logger.warning(
                    "Gemini AI analysis unavailable. "
                    "Displaying quantitative opportunity matrix only."
                )
                gemini_client = None

    has_ai_active: bool = gemini_client is not None

    _display_rebalance_results(
        ranked_scores=ranked_scores,
        asset_dict_map=asset_dict_map,
        recommendations_map=recommendations_map,
        total_val=total_val,
        has_ai=has_ai_active,
        verbose=verbose,
    )

    advisories_ctx: list[dict[str, Any]] = export_outputs(
        ranked_scores=ranked_scores,
        asset_dict_map=asset_dict_map,
        recommendations_map=recommendations_map,
        total_val=total_val,
        has_ai=has_ai_active,
    )

    if "pytest" not in sys.modules:
        try:
            timestamp_key: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            advisories_map_db: dict[str, dict[str, Any]] = {
                adv["symbol"]: adv for adv in advisories_ctx
            }
            opportunity_repo.save_opportunity_report(
                timestamp=timestamp_key,
                total_value_eur=total_val,
                has_ai=has_ai_active,
                ranked_scores=ranked_scores,
                asset_dict_map=asset_dict_map,
                recommendations_map=recommendations_map,
                advisories_map=advisories_map_db,
            )
            logger.success(
                "Successfully persisted opportunity report into SQLite database."
            )
        except Exception as err:
            logger.error(f"Failed to save opportunity report to database: {err}")

    # Dispatch Discord notification if explicitly requested
    if notify and not skip_ai:
        send_discord_notification(
            ranked_assets=ranked_scores,
            recommendations_map=recommendations_map,
            total_portfolio_value=total_val,
        )


if __name__ == "__main__":
    app()
