"""Unit tests for the PortfolioAnalyticsEngine class."""

from __future__ import annotations

from src.core.models import (
    Asset,
    DashboardOverview,
    PortfolioTimeSeries,
)
from src.core.portfolio_analytics import PortfolioAnalyticsEngine
from src.infra.database.finance_sql_extraction import (
    AssetHistoricalRecord,
    PortfolioHistoricalRecord,
)


def test_compute_portfolio_time_series_ath_and_drawdown() -> None:
    """Tests ATH tracking and drawdown calculations over time."""
    engine: PortfolioAnalyticsEngine = PortfolioAnalyticsEngine()
    records: list[PortfolioHistoricalRecord] = [
        PortfolioHistoricalRecord(snapshot_date="2026-01-01", total_value_eur=1000.0),
        PortfolioHistoricalRecord(snapshot_date="2026-02-01", total_value_eur=1200.0),
        PortfolioHistoricalRecord(snapshot_date="2026-03-01", total_value_eur=900.0),
    ]

    res: PortfolioTimeSeries = engine.compute_portfolio_time_series(records)

    assert len(res.value_history) == 3
    assert res.ath_history[0].value == 1000.0
    assert res.ath_history[1].value == 1200.0
    assert res.ath_history[2].value == 1200.0

    assert res.drawdown_history[0].value == 0.0
    assert res.drawdown_history[1].value == 0.0
    assert res.drawdown_history[2].value == -25.0


def test_build_dashboard_overview_complete() -> None:
    """Tests orchestrating complete dashboard overview data structure."""
    engine: PortfolioAnalyticsEngine = PortfolioAnalyticsEngine()
    p_records: list[PortfolioHistoricalRecord] = [
        PortfolioHistoricalRecord(snapshot_date="2026-01-01", total_value_eur=1000.0),
        PortfolioHistoricalRecord(snapshot_date="2026-02-01", total_value_eur=1200.0),
    ]
    a_records: list[AssetHistoricalRecord] = [
        AssetHistoricalRecord(
            snapshot_date="2026-01-01",
            asset_ticker="AAPL",
            asset_name="Apple",
            asset_type="STOCK",
            quantity=2.0,
            value_eur=300.0,
        ),
        AssetHistoricalRecord(
            snapshot_date="2026-01-01",
            asset_ticker="VWCE.DE",
            asset_name="Vanguard",
            asset_type="ETF",
            quantity=10.0,
            value_eur=700.0,
        ),
        AssetHistoricalRecord(
            snapshot_date="2026-02-01",
            asset_ticker="AAPL",
            asset_name="Apple",
            asset_type="STOCK",
            quantity=2.0,
            value_eur=400.0,
        ),
    ]
    assets_config: list[Asset] = [
        Asset(
            name="Apple",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            quantity=2.0,
            average_buy_price=150.0,
            asset_type="STOCK",
        ),
        Asset(
            name="Vanguard",
            isin="IE00BK5BQT33",
            yahoo_ticker="VWCE.DE",
            quantity=10.0,
            average_buy_price=68.0,
            asset_type="ETF",
        ),
    ]

    overview: DashboardOverview = engine.build_dashboard_overview(
        asset_records=a_records,
        portfolio_records=p_records,
        current_assets=assets_config,
    )

    assert len(overview.asset_series) == 2
    assert len(overview.class_series) == 2
    assert overview.top_growth_contributor == "AAPL"
    assert overview.max_drawdown_percent == 0.0


def test_build_dashboard_overview_empty_records() -> None:
    """Tests overview creation when historical records are empty."""
    engine: PortfolioAnalyticsEngine = PortfolioAnalyticsEngine()
    overview: DashboardOverview = engine.build_dashboard_overview(
        asset_records=[],
        portfolio_records=[],
        current_assets=[],
    )

    assert overview.portfolio_history.value_history == []
    assert overview.asset_series == []
    assert overview.class_series == []
    assert overview.asset_summaries == []
    assert overview.top_growth_contributor is None
    assert overview.max_drawdown_percent == 0.0
