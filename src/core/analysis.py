"""This file contains functions for analyzing portfolio performance, asset
exposures, and deterministic fundamental quality tier evaluations using Pandas
vectorization.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.core.exceptions import StorageError
from src.core.exposure import ExposureEngine
from src.core.models import Asset, ETFDetails, PortfolioSnapshot, StockDetails
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import (
    HistoryRepository,
    PortfolioRepository,
    SqliteHistoryRepository,
    SqlitePortfolioRepository,
)
from src.infra.database.connection import DEFAULT_DB_PATH
from src.utils.logger.logger import logger


@dataclass
class PortfolioExposure:
    """Aggregated portfolio exposure across sectors and countries."""

    sector_exposure: dict[str, float] = field(default_factory=dict)
    country_exposure: dict[str, float] = field(default_factory=dict)
    total_etf_value_eur: float = 0.0


def calculate_portfolio_exposure(
    snapshot: PortfolioSnapshot,
    portfolio_repo: PortfolioRepository | None = None,
    etf_provider: ETFProvider | None = None,
    stock_provider: StockProvider | None = None,
) -> PortfolioExposure:
    """Calculates consolidated value-weighted sector and country exposure.

    Deprecated: use ExposureEngine.calculate_consolidated_exposure() instead.
    """
    warnings.warn(
        "calculate_portfolio_exposure is deprecated; "
        "use ExposureEngine.calculate_consolidated_exposure() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    engine = ExposureEngine(
        etf_provider=etf_provider,
        stock_provider=stock_provider,
        portfolio_repo=portfolio_repo,
    )
    sector_pcts, country_pcts = engine.calculate_consolidated_exposure(snapshot)
    return PortfolioExposure(
        sector_exposure=sector_pcts,
        country_exposure=country_pcts,
    )


def analyze_overall_performance(
    portfolio_repo: PortfolioRepository | None = None,
    history_repo: HistoryRepository | None = None,
) -> None:
    """Analyzes performance of individual assets and
    the overall portfolio using vectorised DataFrames.
    """
    logger.section("Portfolio Performance Analysis")

    p_repo: PortfolioRepository = portfolio_repo or SqlitePortfolioRepository(
        DEFAULT_DB_PATH
    )
    h_repo: HistoryRepository = history_repo or SqliteHistoryRepository(DEFAULT_DB_PATH)

    try:
        assets: list[Asset] = p_repo.load_assets()
        history: list[PortfolioSnapshot] = h_repo.load_history()

        if not history:
            logger.warning("History storage is empty. Cannot perform analysis.")
            return

        latest_snapshot: PortfolioSnapshot = history[-1]
    except StorageError as e:
        logger.error(f"Could not read data from storage: {e}")
        return

    latest_asset_values: dict[str, float] = {
        asset.isin: asset.value_eur
        for asset in latest_snapshot.assets_snapshot
        if asset.isin
    }

    performance_records: list[dict[str, Any]] = []

    for asset in assets:
        acquisition_cost: float = asset.acquisition_cost
        latest_value: float | None = (
            latest_asset_values.get(asset.isin) if asset.isin else None
        )

        if latest_value is None:
            logger.warning(f"No recent market data found for {asset.name}. Skipping.")
            continue

        performance_records.append(
            {
                "name": asset.name,
                "acquisition_cost": acquisition_cost,
                "latest_value": latest_value,
                "absolute_gain": latest_value - acquisition_cost,
            }
        )

    if not performance_records:
        logger.warning("No valid asset performance records found.")
        return

    df_perf: pd.DataFrame = pd.DataFrame(performance_records)

    for _, row in df_perf.iterrows():
        name: str = str(row["name"])
        acq_cost: float = float(row["acquisition_cost"])
        lat_val: float = float(row["latest_value"])
        abs_gain: float = float(row["absolute_gain"])

        logger.subsection(name)
        logger.info(f"Acquisition Cost: {acq_cost:.2f} EUR")
        logger.info(f"Latest Market Value: {lat_val:.2f} EUR")

        if abs_gain >= 0:
            logger.success(f"Absolute Gain: +{abs_gain:.2f} EUR")
        else:
            logger.warning(f"Absolute Loss: {abs_gain:.2f} EUR")

    logger.section("Global Analysis")

    total_acquisition_cost: float = float(df_perf["acquisition_cost"].sum())
    total_latest_value: float = float(df_perf["latest_value"].sum())
    total_absolute_gain: float = float(df_perf["absolute_gain"].sum())

    logger.info(f"Total Acquisition Cost: {total_acquisition_cost:.2f} EUR")
    logger.info(f"Latest Market Value:   {total_latest_value:.2f} EUR")

    if total_absolute_gain >= 0:
        logger.success(f"Absolute Gain: +{total_absolute_gain:.2f} EUR")
    else:
        logger.warning(f"Absolute Loss: {total_absolute_gain:.2f} EUR")

    roi_percentage: float = (
        (total_absolute_gain / total_acquisition_cost) * 100.0
        if total_acquisition_cost != 0.0
        else 0.0
    )

    if roi_percentage >= 0:
        logger.success(f"Return on Investment (ROI): +{roi_percentage:.2f}%")
    else:
        logger.warning(f"Return on Investment (ROI): {roi_percentage:.2f}%")


def evaluate_stock_quality(details: StockDetails) -> dict[str, Any]:
    """Evaluates stock fundamental health deterministically (0-100 score)
    and classifies it into Quality Tiers (Tier A, Tier B, Tier C) according to
    established fundamental criteria and knockout rules.
    """
    score: int = 0
    max_score: int = 100

    # 1. Operating Margin (25 pts max)
    margin: float | None = details.profit_margins_pct
    if margin is not None:
        if margin >= 20.0:
            score += 25
        elif margin >= 10.0:
            score += 15

    # 2. Revenue Growth YoY (25 pts max)
    rev_growth: float | None = details.revenue_growth_pct
    if rev_growth is not None:
        if rev_growth >= 8.0:
            score += 25
        elif rev_growth >= 3.0:
            score += 15

    # 3. Balance Sheet Health - Debt to Equity (25 pts max)
    debt_eq: float | None = details.total_debt_to_equity
    normalized_de: float | None = None
    if debt_eq is not None:
        normalized_de = debt_eq / 100.0 if debt_eq > 10.0 else debt_eq
        if normalized_de <= 1.0:
            score += 25
        elif normalized_de <= 2.0:
            score += 15
    else:
        score += 12

    # 4. Earnings Growth (25 pts max)
    earn_growth: float | None = details.earnings_growth_pct
    if earn_growth is not None:
        if earn_growth >= 10.0:
            score += 25
        elif earn_growth >= 5.0:
            score += 15

    # --- Knockout Rules & Tier Assignment ---
    tier: str = "Tier B"
    is_knockout_c: bool = False

    if margin is not None and margin < 0.0:
        is_knockout_c = True
    elif debt_eq is not None and debt_eq > 250.0:
        is_knockout_c = True

    if is_knockout_c:
        tier = "Tier C"
    else:
        de_val: float = debt_eq if debt_eq is not None else 0.0
        margin_val: float = margin if margin is not None else 0.0
        if score >= 80 and margin_val > 10.0 and de_val <= 150.0:
            tier = "Tier A"
        elif score >= 50:
            tier = "Tier B"
        else:
            tier = "Tier C"

    # --- Diagnostic Bull & Bear Cases ---
    bull_points: list[str] = []
    bear_points: list[str] = []

    if margin is not None and margin >= 15.0:
        bull_points.append(f"Strong operating profit margins ({margin:.1f}%)")
    else:
        bear_points.append("Compressed or subdued operating margins")

    if rev_growth is not None and rev_growth >= 5.0:
        bull_points.append(f"Healthy revenue expansion ({rev_growth:.1f}% YoY)")
    else:
        bear_points.append("Slow or stagnant top-line revenue growth")

    if debt_eq is not None:
        if debt_eq <= 100.0:
            bull_points.append("Conservative capital structure and low leverage")
        else:
            bear_points.append(f"Elevated debt-to-equity ratio ({debt_eq:.1f})")
    else:
        bear_points.append("Debt and leverage metrics unavailable")

    if not bull_points:
        bull_points.append("Established business model with stable market presence")
    if not bear_points:
        bear_points.append("No critical balance sheet vulnerabilities detected")

    # --- Valuation Status ---
    valuation_status: str = "Fair Value"
    pe: float | None = details.pe_ratio
    if pe is not None:
        if pe < 15.0:
            valuation_status = "Undervalued"
        elif pe > 30.0:
            valuation_status = "Overvalued"
        else:
            valuation_status = "Fair Value"

    return {
        "score": score,
        "max_score": max_score,
        "tier": tier,
        "bull_case": bull_points,
        "bear_case": bear_points,
        "valuation_status": valuation_status,
    }


def evaluate_etf_quality(
    details: ETFDetails,
    aum_eur: float | None = None,
    age_years: float | None = None,
) -> dict[str, Any]:
    """Classifies ETF quality based on TER, Assets Under Management (AUM),
    and fund age, protecting against liquidity and closure risks.
    """
    ter: float | None = details.ter_pct
    tier: str = "Tier B"

    is_tier_a: bool = True
    if ter is not None and ter > 0.20:
        is_tier_a = False
    if aum_eur is not None and aum_eur <= 500_000_000.0:
        is_tier_a = False
    if age_years is not None and age_years <= 3.0:
        is_tier_a = False

    if is_tier_a and (ter is not None or aum_eur is not None or age_years is not None):
        tier = "Tier A"
    else:
        is_tier_c: bool = False
        if ter is not None and ter > 0.45:
            is_tier_c = True
        if aum_eur is not None and aum_eur < 100_000_000.0:
            is_tier_c = True

        if is_tier_c:
            tier = "Tier C"
        else:
            tier = "Tier B"

    ter_str: str = f"{ter:.2f}%" if ter is not None else "N/A"
    aum_str: str = f"{aum_eur / 1e6:,.1f}M€" if aum_eur is not None else "N/A"

    return {
        "score": 100 if tier == "Tier A" else (70 if tier == "Tier B" else 40),
        "max_score": 100,
        "tier": tier,
        "bull_case": [
            f"Attractive cost efficiency (TER: {ter_str})",
            f"Fund scale and liquidity (AUM: {aum_str})",
        ],
        "bear_case": [
            "Market systemic exposure without individual stock selection",
            "Regulatory or structural tracking risks",
        ],
        "valuation_status": "Fair Value",
    }
