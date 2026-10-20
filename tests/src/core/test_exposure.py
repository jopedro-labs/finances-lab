"""Unit tests for ExposureEngine in src/core/exposure.py covering all scenarios."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.exposure import ExposureEngine
from src.core.models import (
    Asset,
    CountryExposure,
    ETFDetails,
    Holding,
    PortfolioSnapshot,
    SectorExposure,
    StockDetails,
)


def test_exposure_engine_zero_portfolio_value() -> None:
    """Validates exposure engine returns empty dicts when portfolio value is zero."""
    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21 12:00:00", total_value_eur=0.0, assets_snapshot=[]
    )
    engine: ExposureEngine = ExposureEngine()
    sectors: dict[str, float]
    countries: dict[str, float]
    sectors, countries = engine.calculate_consolidated_exposure(snapshot)

    assert sectors == {}
    assert countries == {}
    assert engine.calculate_company_exposure(snapshot) == {}


def test_exposure_engine_load_assets_exception() -> None:
    """Validates exposure engine handles repository load errors gracefully."""
    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.side_effect = Exception("Storage error")

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21 12:00:00",
        total_value_eur=1000.0,
        assets_snapshot=[MagicMock(isin="US0378331005", value_eur=1000.0)],
    )

    engine: ExposureEngine = ExposureEngine(portfolio_repo=mock_repo)
    sectors: dict[str, float]
    countries: dict[str, float]
    sectors, countries = engine.calculate_consolidated_exposure(snapshot)

    assert sectors == {}
    assert countries == {}


def test_exposure_engine_stock_and_etf_lookthrough() -> None:
    """Validates consolidated look-through exposure
    for stocks and ETFs with breakdowns."""
    mock_etf_provider: MagicMock = MagicMock()
    mock_stock_provider: MagicMock = MagicMock()
    mock_repo: MagicMock = MagicMock()

    asset_stock: Asset = Asset(
        isin="US0378331005",
        name="Apple",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=100.0,
        asset_type="STOCK",
    )
    asset_etf: Asset = Asset(
        isin="IE00B4L5Y983",
        name="Core MSCI World",
        yahoo_ticker="EUNL.DE",
        quantity=5.0,
        average_buy_price=50.0,
        asset_type="ETF",
    )

    mock_repo.load_assets.return_value = [asset_stock, asset_etf]

    mock_stock_provider.get_details.return_value = StockDetails(sector="Technology")
    mock_etf_provider.get_details.return_value = ETFDetails(
        sector_breakdown=[SectorExposure(sector_name="Technology", weight_pct=60.0)],
        country_breakdown=[
            CountryExposure(country_name="United States", weight_pct=70.0)
        ],
        holdings=[
            Holding(name="NVIDIA", isin="US67066G1040", ticker="NVDA", weight_pct=20.0)
        ],
        ter_pct=0.20,
    )

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21 12:00:00",
        total_value_eur=2000.0,
        assets_snapshot=[
            MagicMock(isin="US0378331005", value_eur=1000.0),
            MagicMock(isin="IE00B4L5Y983", value_eur=1000.0),
        ],
    )

    engine: ExposureEngine = ExposureEngine(
        etf_provider=mock_etf_provider,
        stock_provider=mock_stock_provider,
        portfolio_repo=mock_repo,
    )

    sectors: dict[str, float]
    countries: dict[str, float]
    sectors, countries = engine.calculate_consolidated_exposure(snapshot)
    companies: dict[str, float] = engine.calculate_company_exposure(snapshot)

    assert "Technology" in sectors
    assert "Unknown" in sectors
    assert "United States" in countries
    assert "Unknown" in countries
    assert len(companies) > 0

    violations: list[str] = engine.validate_exposure_limits(sectors, countries)
    assert isinstance(violations, list)

    company_violations: list[str] = engine.validate_company_limits(companies)
    assert isinstance(company_violations, list)


def test_exposure_engine_missing_etf_and_stock_details() -> None:
    """Validates fallback behavior when provider returns None for ETF and stock."""
    mock_etf_provider: MagicMock = MagicMock()
    mock_stock_provider: MagicMock = MagicMock()
    mock_repo: MagicMock = MagicMock()

    asset_etf: Asset = Asset(
        isin="IE00B4L5Y983",
        name="Unknown ETF",
        yahoo_ticker="ETF",
        quantity=1.0,
        average_buy_price=100.0,
        asset_type="ETF",
    )
    asset_stock: Asset = Asset(
        isin="US0000000001",
        name="Unknown Stock",
        yahoo_ticker="UNKN",
        quantity=1.0,
        average_buy_price=100.0,
        asset_type="STOCK",
    )

    mock_repo.load_assets.return_value = [asset_etf, asset_stock]
    mock_etf_provider.get_details.return_value = None
    mock_stock_provider.get_details.return_value = None

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21",
        total_value_eur=200.0,
        assets_snapshot=[
            MagicMock(isin="IE00B4L5Y983", value_eur=100.0),
            MagicMock(isin="US0000000001", value_eur=100.0),
        ],
    )

    engine: ExposureEngine = ExposureEngine(
        etf_provider=mock_etf_provider,
        stock_provider=mock_stock_provider,
        portfolio_repo=mock_repo,
    )

    sectors: dict[str, float]
    countries: dict[str, float]
    sectors, countries = engine.calculate_consolidated_exposure(snapshot)

    assert sectors.get("Unknown") == 100.0
    assert countries.get("Unknown") == 100.0


def test_exposure_engine_skips_zero_value_assets() -> None:
    """Validates exposure calculations skip assets with zero or negative value."""
    mock_etf_provider: MagicMock = MagicMock()
    mock_stock_provider: MagicMock = MagicMock()
    mock_repo: MagicMock = MagicMock()

    asset: Asset = Asset(
        isin="US0378331005",
        name="Apple",
        yahoo_ticker="AAPL",
        quantity=0.0,
        average_buy_price=100.0,
        asset_type="STOCK",
    )
    mock_repo.load_assets.return_value = [asset]

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21",
        total_value_eur=100.0,
        assets_snapshot=[MagicMock(isin="US0378331005", value_eur=0.0)],
    )

    engine: ExposureEngine = ExposureEngine(
        etf_provider=mock_etf_provider,
        stock_provider=mock_stock_provider,
        portfolio_repo=mock_repo,
    )

    sectors: dict[str, float]
    countries: dict[str, float]
    sectors, countries = engine.calculate_consolidated_exposure(snapshot)

    assert sectors == {}
    assert countries == {}
    assert engine.calculate_company_exposure(snapshot) == {}


def test_calculate_penalty_factor_no_breach() -> None:
    """Verifies penalty factor is 1.0 when exposures are within policy limits."""
    engine: ExposureEngine = ExposureEngine()
    penalty: float = engine.calculate_penalty_factor(
        sector="Technology",
        country="United States",
        sector_percentages={"Technology": 40.0},
        country_percentages={"United States": 50.0},
    )
    assert penalty == 1.0


def test_calculate_penalty_factor_tech_and_country_breach() -> None:
    """Verifies multiplicative penalty calculation when limits are exceeded."""
    engine: ExposureEngine = ExposureEngine()
    penalty: float = engine.calculate_penalty_factor(
        sector="Technology",
        country="United States",
        sector_percentages={"Technology": 75.0},
        country_percentages={"United States": 90.0},
    )
    assert penalty < 1.0
    assert round(penalty, 3) == 0.765


def test_calculate_penalty_factor_ignores_unknown() -> None:
    """Verifies 'Unknown' sector and country do not trigger penalties."""
    engine: ExposureEngine = ExposureEngine()
    penalty: float = engine.calculate_penalty_factor(
        sector="Unknown",
        country="Unknown",
        sector_percentages={"Unknown": 100.0},
        country_percentages={"Unknown": 100.0},
    )
    assert penalty == 1.0


def test_validate_exposure_limits_violations() -> None:
    """Verifies policy limit violations detection for sectors and countries."""
    engine: ExposureEngine = ExposureEngine()
    sector_pcts: dict[str, float] = {
        "Technology": 55.0,
        "Healthcare": 20.0,
        "Unknown": 90.0,
    }
    country_pcts: dict[str, float] = {
        "United States": 65.0,
        "Unknown": 80.0,
    }

    violations: list[str] = engine.validate_exposure_limits(sector_pcts, country_pcts)

    assert len(violations) == 3
    assert any("Technology" in v for v in violations)
    assert any("Healthcare" in v for v in violations)
    assert any("United States" in v for v in violations)


def test_validate_company_limits_violations() -> None:
    """Verifies company exposure policy violation detection."""
    engine: ExposureEngine = ExposureEngine()
    company_pcts: dict[str, float] = {
        "Apple Inc.": 20.0,
        "Microsoft": 10.0,
    }

    violations: list[str] = engine.validate_company_limits(company_pcts)

    assert len(violations) == 1
    assert "Apple Inc." in violations[0]


def test_calculate_company_exposure_combines_stock_and_etf_holdings() -> None:
    """Verifies look-through company aggregation combining
    direct stock and ETF holdings."""
    mock_etf_provider: MagicMock = MagicMock()
    mock_stock_provider: MagicMock = MagicMock()
    mock_repo: MagicMock = MagicMock()

    stock_asset: Asset = Asset(
        isin="US0378331005",
        name="Apple Inc.",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=150.0,
        asset_type="STOCK",
    )
    etf_asset: Asset = Asset(
        isin="IE00B4L5Y983",
        name="iShares Core MSCI World",
        yahoo_ticker="EUNL.DE",
        quantity=10.0,
        average_buy_price=70.0,
        asset_type="ETF",
    )

    mock_repo.load_assets.return_value = [stock_asset, etf_asset]

    mock_etf_provider.get_details.return_value = ETFDetails(
        sector_breakdown=[],
        country_breakdown=[],
        holdings=[
            Holding(
                name="Apple Inc.", isin="US0378331005", ticker="AAPL", weight_pct=10.0
            ),
            Holding(
                name="NVIDIA Corp", isin="US67066G1040", ticker="NVDA", weight_pct=5.0
            ),
        ],
        ter_pct=0.20,
    )

    snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-21 12:00:00",
        total_value_eur=1000.0,
        assets_snapshot=[
            MagicMock(isin="US0378331005", value_eur=500.0),
            MagicMock(isin="IE00B4L5Y983", value_eur=500.0),
        ],
    )

    engine: ExposureEngine = ExposureEngine(
        etf_provider=mock_etf_provider,
        stock_provider=mock_stock_provider,
        portfolio_repo=mock_repo,
    )

    company_pcts: dict[str, float] = engine.calculate_company_exposure(snapshot)

    assert company_pcts.get("Apple Inc.") == 55.0
    assert company_pcts.get("NVIDIA Corp") == 2.5
