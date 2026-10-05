"""Comprehensive unit tests for src/core/analysis.py covering portfolio exposure,

performance analysis, stock quality evaluation, and ETF quality evaluation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.analysis import (
    PortfolioExposure,
    analyze_overall_performance,
    calculate_portfolio_exposure,
    evaluate_etf_quality,
    evaluate_stock_quality,
)
from src.core.exceptions import StorageError
from src.core.models import (
    Asset,
    AssetSnapshot,
    ETFDetails,
    PortfolioSnapshot,
    StockDetails,
)


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_gain_scenario(mock_logger: MagicMock) -> None:
    """Validates calculations and log outputs for individual assets and gain."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="Apple",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            quantity=10.0,
            average_buy_price=100.0,
        ),
    ]
    mock_h_repo: MagicMock = MagicMock()
    mock_h_repo.load_history.return_value = [
        PortfolioSnapshot(
            timestamp="2026-08-15T20:00:00",
            total_value_eur=1500.0,
            assets_snapshot=[
                AssetSnapshot(
                    name="Apple",
                    isin="US0378331005",
                    yahoo_ticker="AAPL",
                    native_price=150.0,
                    native_currency="USD",
                    value_eur=1500.0,
                )
            ],
        )
    ]

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.success.assert_any_call("Absolute Gain: +500.00 EUR")
    mock_logger.success.assert_any_call("Return on Investment (ROI): +50.00%")


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_loss_scenario(mock_logger: MagicMock) -> None:
    """Validates log outputs when portfolio produces an absolute loss."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="Tesla",
            isin="US88160R1014",
            yahoo_ticker="TSLA",
            quantity=10.0,
            average_buy_price=200.0,
        )
    ]
    mock_h_repo: MagicMock = MagicMock()
    mock_h_repo.load_history.return_value = [
        PortfolioSnapshot(
            timestamp="2026-08-15T20:00:00",
            total_value_eur=1000.0,
            assets_snapshot=[
                AssetSnapshot(
                    name="Tesla",
                    isin="US88160R1014",
                    yahoo_ticker="TSLA",
                    native_price=100.0,
                    native_currency="USD",
                    value_eur=1000.0,
                )
            ],
        )
    ]

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.warning.assert_any_call("Absolute Loss: -1000.00 EUR")
    mock_logger.warning.assert_any_call("Return on Investment (ROI): -50.00%")


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_empty_history(mock_logger: MagicMock) -> None:
    """Tests handling when history storage is empty."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = []
    mock_h_repo: MagicMock = MagicMock()
    mock_h_repo.load_history.return_value = []

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.warning.assert_called_with(
        "History storage is empty. Cannot perform analysis."
    )


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_storage_error(mock_logger: MagicMock) -> None:
    """Tests storage error handling during analysis."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.side_effect = StorageError("Storage failure")
    mock_h_repo: MagicMock = MagicMock()

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.error.assert_called_with(
        "Could not read data from storage: Storage failure"
    )


@patch("src.core.analysis.SqliteHistoryRepository")
@patch("src.core.analysis.SqlitePortfolioRepository")
@patch("src.core.analysis.logger")
def test_analyze_overall_performance_defaults(
    mock_logger: MagicMock,
    mock_p_cls: MagicMock,
    mock_h_cls: MagicMock,
) -> None:
    """Tests default repository instantiation."""
    mock_p_cls.return_value.load_assets.return_value = []
    mock_h_cls.return_value.load_history.return_value = []

    analyze_overall_performance(portfolio_repo=None, history_repo=None)
    mock_p_cls.assert_called_once()
    mock_h_cls.assert_called_once()


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_asset_without_isin_skipped(
    mock_logger: MagicMock,
) -> None:
    """Validates that assets without ISIN are skipped with a warning."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="No ISIN Asset",
            isin="",
            yahoo_ticker="NOIS",
            quantity=1.0,
            average_buy_price=100.0,
        )
    ]
    mock_h_repo: MagicMock = MagicMock()
    mock_h_repo.load_history.return_value = [
        PortfolioSnapshot(
            timestamp="2026-08-15T20:00:00",
            total_value_eur=100.0,
            assets_snapshot=[],
        )
    ]

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.warning.assert_any_call(
        "No recent market data found for No ISIN Asset. Skipping."
    )


@patch("src.core.analysis.logger")
def test_analyze_overall_performance_no_valid_records(
    mock_logger: MagicMock,
) -> None:
    """Validates warning when all assets have no recent market data."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="Orphan",
            isin="US9999999999",
            yahoo_ticker="ORPH",
            quantity=1.0,
            average_buy_price=50.0,
        )
    ]
    mock_h_repo: MagicMock = MagicMock()
    mock_h_repo.load_history.return_value = [
        PortfolioSnapshot(
            timestamp="2026-08-15T20:00:00",
            total_value_eur=200.0,
            assets_snapshot=[],
        )
    ]

    analyze_overall_performance(portfolio_repo=mock_p_repo, history_repo=mock_h_repo)
    mock_logger.warning.assert_any_call("No valid asset performance records found.")


def test_calculate_portfolio_exposure_comprehensive() -> None:
    """Tests portfolio exposure calculation with various asset types and edges."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="ETF World",
            isin="IE00B4L5Y983",
            yahoo_ticker="EUNL.DE",
            asset_type="ETF",
            quantity=10.0,
            average_buy_price=50.0,
        ),
    ]

    mock_etf_prov: MagicMock = MagicMock()
    mock_etf_prov.get_details.return_value = ETFDetails(
        holdings=[],
        sector_breakdown=[SimpleNamespace(sector_name="Tech", weight_pct=100.0)],
        country_breakdown=[SimpleNamespace(country_name="USA", weight_pct=100.0)],
    )

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-22",
        total_value_eur=400.0,
        assets_snapshot=[
            AssetSnapshot(
                name="ETF World",
                isin="IE00B4L5Y983",
                yahoo_ticker="EUNL.DE",
                native_price=40.0,
                native_currency="EUR",
                value_eur=400.0,
            ),
        ],
    )

    with pytest.warns(DeprecationWarning):
        exposure: PortfolioExposure = calculate_portfolio_exposure(
            snapshot=snapshot,
            portfolio_repo=mock_p_repo,
            etf_provider=mock_etf_prov,
        )
    assert "Tech" in exposure.sector_exposure


def test_calculate_portfolio_exposure_stock_sector_fallback() -> None:
    """Tests stock exposure uses provider sector and defaults country to US."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="Apple",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            asset_type="STOCK",
            quantity=1.0,
            average_buy_price=180.0,
        ),
    ]

    mock_stock_prov: MagicMock = MagicMock()
    mock_stock_prov.get_details.return_value = MagicMock(sector="Technology")

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-22",
        total_value_eur=200.0,
        assets_snapshot=[
            AssetSnapshot(
                name="Apple",
                isin="US0378331005",
                yahoo_ticker="AAPL",
                native_price=200.0,
                native_currency="USD",
                value_eur=200.0,
            )
        ],
    )

    with pytest.warns(DeprecationWarning):
        exposure: PortfolioExposure = calculate_portfolio_exposure(
            snapshot=snapshot,
            portfolio_repo=mock_p_repo,
            stock_provider=mock_stock_prov,
        )
    assert "Technology" in exposure.sector_exposure
    assert "United States" in exposure.country_exposure


def test_calculate_portfolio_exposure_stock_no_sector() -> None:
    """Tests stock exposure falls back to 'Unknown' when sector is None."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="NoSector",
            isin="US1111111111",
            yahoo_ticker="NOSEC",
            asset_type="STOCK",
            quantity=1.0,
            average_buy_price=50.0,
        ),
    ]

    mock_stock_prov: MagicMock = MagicMock()
    mock_stock_prov.get_details.return_value = MagicMock(sector=None)

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-22",
        total_value_eur=100.0,
        assets_snapshot=[
            AssetSnapshot(
                name="NoSector",
                isin="US1111111111",
                yahoo_ticker="NOSEC",
                native_price=100.0,
                native_currency="USD",
                value_eur=100.0,
            )
        ],
    )

    with pytest.warns(DeprecationWarning):
        exposure: PortfolioExposure = calculate_portfolio_exposure(
            snapshot=snapshot,
            portfolio_repo=mock_p_repo,
            stock_provider=mock_stock_prov,
        )
    assert "Unknown" in exposure.sector_exposure


def test_calculate_portfolio_exposure_etf_details_none() -> None:
    """Tests deprecated shim emits DeprecationWarning."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.return_value = [
        Asset(
            name="ETF None",
            isin="IE00000000001",
            yahoo_ticker="NONE.DE",
            asset_type="ETF",
            quantity=1.0,
            average_buy_price=50.0,
        ),
    ]

    mock_etf_prov: MagicMock = MagicMock()
    mock_etf_prov.get_details.return_value = None

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-22",
        total_value_eur=100.0,
        assets_snapshot=[
            AssetSnapshot(
                name="ETF None",
                isin="IE00000000001",
                yahoo_ticker="NONE.DE",
                native_price=100.0,
                native_currency="EUR",
                value_eur=100.0,
            )
        ],
    )

    with pytest.warns(DeprecationWarning):
        exposure: PortfolioExposure = calculate_portfolio_exposure(
            snapshot=snapshot,
            portfolio_repo=mock_p_repo,
            etf_provider=mock_etf_prov,
        )
    assert isinstance(exposure.sector_exposure, dict)
    assert isinstance(exposure.country_exposure, dict)


@patch("src.core.analysis.logger")
def test_calculate_portfolio_exposure_error(mock_logger: MagicMock) -> None:
    """Tests exposure calculation is deprecated and delegates to ExposureEngine."""
    mock_p_repo: MagicMock = MagicMock()
    mock_p_repo.load_assets.side_effect = Exception("DB error")
    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-22", total_value_eur=100.0, assets_snapshot=[]
    )

    with pytest.warns(DeprecationWarning):
        exposure: PortfolioExposure = calculate_portfolio_exposure(
            snapshot=snapshot, portfolio_repo=mock_p_repo
        )
    assert exposure.total_etf_value_eur == 0.0


# ==============================================================================
# evaluate_stock_quality tests
# ==============================================================================


def test_evaluate_stock_quality_tier_a() -> None:
    """Validates Tier A assignment: high margin, revenue growth, low D/E."""
    details = StockDetails(
        profit_margins_pct=25.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=15.0,
        pe_ratio=20.0,
    )
    result = evaluate_stock_quality(details)
    assert result["tier"] == "Tier A"
    assert result["score"] == 100
    assert result["valuation_status"] == "Fair Value"


def test_evaluate_stock_quality_tier_b_mid_score() -> None:
    """Validates Tier B for score >=50 that doesn't meet Tier A thresholds."""
    details = StockDetails(
        profit_margins_pct=12.0,
        revenue_growth_pct=4.0,
        total_debt_to_equity=120.0,
        earnings_growth_pct=6.0,
        pe_ratio=25.0,
    )
    result = evaluate_stock_quality(details)
    assert result["tier"] == "Tier B"
    assert result["score"] >= 50


def test_evaluate_stock_quality_tier_c_low_score() -> None:
    """Validates Tier C when score is below 50 and no knockouts."""
    details = StockDetails(
        profit_margins_pct=5.0,
        revenue_growth_pct=1.0,
        total_debt_to_equity=200.0,
        earnings_growth_pct=2.0,
        pe_ratio=25.0,
    )
    result = evaluate_stock_quality(details)
    assert result["tier"] == "Tier C"


def test_evaluate_stock_quality_knockout_negative_margin() -> None:
    """Validates Tier C knockout when operating margin is negative."""
    details = StockDetails(
        profit_margins_pct=-5.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=15.0,
    )
    result = evaluate_stock_quality(details)
    assert result["tier"] == "Tier C"


def test_evaluate_stock_quality_knockout_high_debt() -> None:
    """Validates Tier C knockout when D/E ratio exceeds 250."""
    details = StockDetails(
        profit_margins_pct=20.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=300.0,
        earnings_growth_pct=15.0,
    )
    result = evaluate_stock_quality(details)
    assert result["tier"] == "Tier C"


def test_evaluate_stock_quality_valuation_undervalued() -> None:
    """Validates 'Undervalued' status when P/E < 15."""
    details = StockDetails(
        profit_margins_pct=20.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=15.0,
        pe_ratio=10.0,
    )
    result = evaluate_stock_quality(details)
    assert result["valuation_status"] == "Undervalued"


def test_evaluate_stock_quality_valuation_overvalued() -> None:
    """Validates 'Overvalued' status when P/E > 30."""
    details = StockDetails(
        profit_margins_pct=20.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=15.0,
        pe_ratio=45.0,
    )
    result = evaluate_stock_quality(details)
    assert result["valuation_status"] == "Overvalued"


def test_evaluate_stock_quality_all_none_metrics() -> None:
    """Validates scoring when all optional metrics are None."""
    details = StockDetails()
    result = evaluate_stock_quality(details)
    assert result["tier"] in ("Tier A", "Tier B", "Tier C")
    assert result["score"] == 12  # only D/E none branch grants 12 pts


def test_evaluate_stock_quality_bull_bear_cases_populated() -> None:
    """Validates bull and bear case lists are always non-empty."""
    details_good = StockDetails(
        profit_margins_pct=20.0,
        revenue_growth_pct=8.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=12.0,
    )
    result = evaluate_stock_quality(details_good)
    assert len(result["bull_case"]) >= 1
    assert len(result["bear_case"]) >= 1


# ==============================================================================
# evaluate_etf_quality tests
# ==============================================================================


def test_evaluate_etf_quality_tier_a() -> None:
    """Validates Tier A ETF: TER <=0.20, AUM >500M, age >3 years."""
    etf = ETFDetails(
        ter_pct=0.10, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf, aum_eur=600_000_000.0, age_years=5.0)
    assert result["tier"] == "Tier A"
    assert result["score"] == 100


def test_evaluate_etf_quality_tier_b_high_ter() -> None:
    """Validates Tier B when TER is between 0.20% and 0.45%."""
    etf = ETFDetails(
        ter_pct=0.35, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf)
    assert result["tier"] == "Tier B"
    assert result["score"] == 70


def test_evaluate_etf_quality_tier_c_ter_too_high() -> None:
    """Validates Tier C when TER exceeds 0.45%."""
    etf = ETFDetails(
        ter_pct=0.60, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf)
    assert result["tier"] == "Tier C"
    assert result["score"] == 40


def test_evaluate_etf_quality_tier_c_low_aum() -> None:
    """Validates Tier C when AUM is below 100M€."""
    etf = ETFDetails(
        ter_pct=0.20, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf, aum_eur=50_000_000.0)
    assert result["tier"] == "Tier C"


def test_evaluate_etf_quality_tier_b_young_fund() -> None:
    """Validates Tier B when fund age <= 3 years (fails Tier A)."""
    etf = ETFDetails(
        ter_pct=0.10, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf, aum_eur=600_000_000.0, age_years=2.0)
    assert result["tier"] == "Tier B"


def test_evaluate_etf_quality_no_optional_params() -> None:
    """Validates Tier B default when no AUM or age are provided."""
    etf = ETFDetails(
        ter_pct=None, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    result = evaluate_etf_quality(etf)
    assert result["tier"] == "Tier B"
    assert result["valuation_status"] == "Fair Value"
