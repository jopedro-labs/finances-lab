"""Comprehensive unit tests covering all opportunity_evaluation strategies,
boundary conditions,and portfolio opportunity_evaluation engine ranking logic."""

from typing import Any

import pytest

from src.config import EtfStrategyConfig, StockStrategyConfig
from src.core.opportunity_evaluation.base import AssetScore, AssetType, ScoringStrategy
from src.core.opportunity_evaluation.engine import PortfolioOpportunityEngine
from src.core.opportunity_evaluation.etf_strategy import EtfScoringStrategy
from src.core.opportunity_evaluation.stock_strategy import StockScoringStrategy

# ==============================================================================
# CONFIGURATION VALIDATION TESTS
# ==============================================================================


def test_stock_config_invalid_weights() -> None:
    """Verifies that StockStrategyConfig raises ValueError
    when weights do not sum to 1.0."""
    with pytest.raises(ValueError, match="Stock strategy weights must sum to 1.0"):
        StockStrategyConfig(
            weight_dip=0.40,
            weight_forward_pe=0.40,
            weight_52w_range=0.30,
            weight_allocation=0.30,
        )


def test_etf_config_invalid_weights() -> None:
    """Verifies that EtfStrategyConfig raises ValueError
    when weights do not sum to 1.0."""
    with pytest.raises(ValueError, match="ETF strategy weights must sum to 1.0"):
        EtfStrategyConfig(
            weight_dip=0.50,
            weight_ter=0.50,
            weight_allocation=0.50,
        )


# ==============================================================================
# ETF STRATEGY TESTS
# ==============================================================================


def test_etf_dip_score_all_branches() -> None:
    """Tests ETF dip score across all mathematical boundary conditions."""
    strategy: EtfScoringStrategy = EtfScoringStrategy()

    # Peak or current price <= 0.0
    assert strategy.calculate_dip_score(current_price=0.0, peak_price=100.0) == 0.0
    assert strategy.calculate_dip_score(current_price=100.0, peak_price=0.0) == 0.0
    assert strategy.calculate_dip_score(current_price=-10.0, peak_price=100.0) == 0.0
    assert strategy.calculate_dip_score(current_price=100.0, peak_price=-5.0) == 0.0

    # Negative dip (current_price > peak_price)
    assert strategy.calculate_dip_score(current_price=105.0, peak_price=100.0) == 0.0

    # Minor drop (< dip_min_pct = 5%)
    assert strategy.calculate_dip_score(
        current_price=97.5, peak_price=100.0
    ) == pytest.approx(0.1, abs=1e-4)

    # Sweet spot drop (5% <= dip <= 10% for ETF)
    assert strategy.calculate_dip_score(current_price=95.0, peak_price=100.0) == 1.0
    assert strategy.calculate_dip_score(current_price=90.0, peak_price=100.0) == 1.0

    # Excess drop above dip_max_pct = 10% (penalty decay)
    assert strategy.calculate_dip_score(
        current_price=80.0, peak_price=100.0
    ) == pytest.approx(0.5, abs=1e-4)

    # Extreme drop hitting floor of 0.1
    assert strategy.calculate_dip_score(current_price=50.0, peak_price=100.0) == 0.1


def test_etf_ter_score_all_branches() -> None:
    """Tests ETF TER cost efficiency across missing metadata,
    low, high, and linear decay ranges."""
    strategy: EtfScoringStrategy = EtfScoringStrategy()

    # Missing or negative TER metadata
    assert strategy.calculate_ter_score(ter=None) == 0.5
    assert strategy.calculate_ter_score(ter=-0.05) == 0.5

    # Ultra low-cost ETF (<= ter_low_pct = 0.10%)
    assert strategy.calculate_ter_score(ter=0.05) == 1.0
    assert strategy.calculate_ter_score(ter=0.10) == 1.0

    # High-cost ETF (>= ter_high_pct = 0.50%)
    assert strategy.calculate_ter_score(ter=0.50) == 0.0
    assert strategy.calculate_ter_score(ter=0.60) == 0.0

    # Linear decay between 0.10% and 0.50%
    assert strategy.calculate_ter_score(ter=0.30) == 0.5


def test_etf_allocation_score_all_branches() -> None:
    """Tests underweight allocation gap scoring for ETFs."""
    strategy: EtfScoringStrategy = EtfScoringStrategy()

    # Overweight or on target (gap <= 0.0)
    assert (
        strategy.calculate_allocation_score(
            target_allocation_pct=10.0, current_allocation_pct=10.0
        )
        == 0.0
    )
    assert (
        strategy.calculate_allocation_score(
            target_allocation_pct=10.0, current_allocation_pct=15.0
        )
        == 0.0
    )

    # Absolute gap: 5% gap / 15% normalizer = 0.333 (not relative to target)
    assert strategy.calculate_allocation_score(
        target_allocation_pct=10.0, current_allocation_pct=5.0
    ) == pytest.approx(5.0 / 15.0, abs=1e-4)

    # Small target: 2% gap / 15% normalizer = 0.133 (not capped at 1.0)
    assert strategy.calculate_allocation_score(
        target_allocation_pct=2.0, current_allocation_pct=0.0
    ) == pytest.approx(2.0 / 15.0, abs=1e-4)


def test_etf_calculate_score_composite() -> None:
    """Validates composite ETF scoring with rounding
    and weighted sums."""
    # Use explicit config so the test is independent of .env overrides
    config: EtfStrategyConfig = EtfStrategyConfig(
        weight_dip=0.35,
        weight_ter=0.20,
        weight_allocation=0.45,
        alloc_gap_normalizer_pct=15.0,
    )
    strategy: EtfScoringStrategy = EtfScoringStrategy(config=config)

    score: AssetScore = strategy.calculate_score(
        symbol="EUNL.DE",
        current_price=90.0,
        peak_price=100.0,
        target_allocation_pct=10.0,
        current_allocation_pct=0.0,
        ter=0.10,
    )

    assert score.symbol == "EUNL.DE"
    assert score.asset_type == AssetType.ETF
    assert score.dip_score == 1.0
    assert score.cost_score == 1.0
    # 10% gap / 15% normalizer = 0.6667 (absolute magnitude, not relative to target)
    assert score.allocation_score == pytest.approx(10.0 / 15.0, abs=1e-4)
    # 1.0*0.35 + 1.0*0.20 + 0.6667*0.45 = 0.85
    assert score.total_score == pytest.approx(0.85, abs=1e-4)


# ==============================================================================
# STOCK STRATEGY TESTS
# ==============================================================================


def test_stock_dip_score_all_branches() -> None:
    """Tests stock dip calculation across invalid prices,
    minor drops, sweet-spots, and falling knives."""
    strategy: StockScoringStrategy = StockScoringStrategy()

    # Invalid price or peak
    assert strategy.calculate_dip_score(current_price=0.0, peak_price=100.0) == 0.0
    assert strategy.calculate_dip_score(current_price=100.0, peak_price=0.0) == 0.0
    assert strategy.calculate_dip_score(current_price=-5.0, peak_price=100.0) == 0.0
    assert strategy.calculate_dip_score(current_price=105.0, peak_price=100.0) == 0.0

    # Minor drop (< dip_min_pct = 5%)
    assert strategy.calculate_dip_score(
        current_price=97.0, peak_price=100.0
    ) == pytest.approx(0.12, abs=1e-4)

    # Sweet-spot drop (5% <= dip <= 20%)
    assert strategy.calculate_dip_score(current_price=90.0, peak_price=100.0) == 1.0

    # Falling knife penalty (> 20% drop)
    assert strategy.calculate_dip_score(
        current_price=65.0, peak_price=100.0
    ) == pytest.approx(0.5, abs=1e-4)

    # Extreme drop hitting penalty floor 0.1
    assert strategy.calculate_dip_score(current_price=30.0, peak_price=100.0) == 0.1


def test_stock_pe_score_all_branches() -> None:
    """Tests P/E score calculation for missing metadata,
    earnings growth, stagnation, and contraction."""
    strategy: StockScoringStrategy = StockScoringStrategy()

    # Missing or non-positive P/E data fallback
    assert strategy.calculate_pe_score(trailing_pe=None, forward_pe=20.0) == 0.5
    assert strategy.calculate_pe_score(trailing_pe=20.0, forward_pe=None) == 0.5
    assert strategy.calculate_pe_score(trailing_pe=0.0, forward_pe=20.0) == 0.5
    assert strategy.calculate_pe_score(trailing_pe=20.0, forward_pe=-5.0) == 0.5

    # Earnings growth (Forward P/E < Trailing P/E -> ratio < 1.0)
    assert strategy.calculate_pe_score(trailing_pe=25.0, forward_pe=20.0) == 1.0

    # Moderate earnings growth
    assert strategy.calculate_pe_score(
        trailing_pe=20.0, forward_pe=18.0
    ) == pytest.approx(0.84, abs=1e-4)

    # Stagnation (Forward P/E == Trailing P/E)
    assert strategy.calculate_pe_score(trailing_pe=25.0, forward_pe=25.0) == 0.6

    # Earnings contraction (Forward P/E > Trailing P/E)
    assert strategy.calculate_pe_score(
        trailing_pe=20.0, forward_pe=26.0
    ) == pytest.approx(0.3, abs=1e-4)

    # Severe contraction reaching floor 0.0
    assert strategy.calculate_pe_score(trailing_pe=20.0, forward_pe=40.0) == 0.0


def test_stock_52w_range_score_all_branches() -> None:
    """Tests 52-week position evaluation across all boundary conditions."""
    strategy: StockScoringStrategy = StockScoringStrategy()

    # Missing or invalid range
    assert (
        strategy.calculate_52w_range_score(
            current_price=10.0, low_52w=None, high_52w=20.0
        )
        == 0.5
    )
    assert (
        strategy.calculate_52w_range_score(
            current_price=10.0, low_52w=10.0, high_52w=None
        )
        == 0.5
    )
    assert (
        strategy.calculate_52w_range_score(
            current_price=10.0, low_52w=20.0, high_52w=10.0
        )
        == 0.5
    )
    assert (
        strategy.calculate_52w_range_score(
            current_price=0.0, low_52w=10.0, high_52w=20.0
        )
        == 0.5
    )

    # Price below low_52w (clamped relative_pos = 0.0 <= 0.30 -> score 1.0)
    assert (
        strategy.calculate_52w_range_score(
            current_price=90.0, low_52w=100.0, high_52w=200.0
        )
        == 1.0
    )

    # Bottom 30% of range (relative_pos <= 0.30)
    assert (
        strategy.calculate_52w_range_score(
            current_price=130.0, low_52w=100.0, high_52w=200.0
        )
        == 1.0
    )

    # Linear decay above 30% of range
    assert strategy.calculate_52w_range_score(
        current_price=165.0, low_52w=100.0, high_52w=200.0
    ) == pytest.approx(0.5, abs=1e-4)

    # Price at or above high_52w (clamped relative_pos = 1.0 -> score 0.0)
    assert (
        strategy.calculate_52w_range_score(
            current_price=200.0, low_52w=100.0, high_52w=200.0
        )
        == 0.0
    )
    assert (
        strategy.calculate_52w_range_score(
            current_price=210.0, low_52w=100.0, high_52w=200.0
        )
        == 0.0
    )


def test_stock_calculate_score_composite() -> None:
    """Validates composite stock scoring calculation."""
    strategy: StockScoringStrategy = StockScoringStrategy()

    score: AssetScore = strategy.calculate_score(
        symbol="AAPL",
        current_price=180.0,
        peak_price=200.0,
        target_allocation_pct=15.0,
        current_allocation_pct=5.0,
        trailing_pe=30.0,
        forward_pe=25.0,
        low_52w=150.0,
        high_52w=200.0,
    )

    assert score.symbol == "AAPL"
    assert score.asset_type == AssetType.STOCK
    assert 0.0 <= score.total_score <= 1.0


# ==============================================================================
# PORTFOLIO OPPORTUNITY ENGINE TESTS
# ==============================================================================


def test_engine_ranks_assets_correctly() -> None:
    """Verifies that the opportunity_evaluation engine scores and
    ranks assets in descending order."""
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()

    assets_data: list[dict[str, Any]] = [
        {
            "symbol": "LOW_PRIORITY",
            "asset_type": "ETF",
            "current_price": 100.0,
            "peak_price": 100.0,
            "target_allocation_pct": 10.0,
            "current_allocation_pct": 10.0,
            "ter": 0.60,
        },
        {
            "symbol": "HIGH_PRIORITY",
            "asset_type": "ETF",
            "current_price": 93.0,
            "peak_price": 100.0,
            "target_allocation_pct": 20.0,
            "current_allocation_pct": 10.0,
            "ter": 0.07,
        },
    ]

    scores: list[AssetScore] = engine.rank_assets(assets_data)

    assert len(scores) == 2
    assert scores[0].symbol == "HIGH_PRIORITY"
    assert scores[1].symbol == "LOW_PRIORITY"
    assert scores[0].total_score > scores[1].total_score


def test_engine_handles_asset_type_enum_instance() -> None:
    """Verifies engine handles AssetType enum instances directly."""
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()

    assets_data: list[dict[str, Any]] = [
        {
            "symbol": "AAPL",
            "asset_type": AssetType.STOCK,
            "current_price": 180.0,
            "peak_price": 200.0,
            "target_allocation_pct": 15.0,
            "current_allocation_pct": 5.0,
        }
    ]

    scores: list[AssetScore] = engine.rank_assets(assets_data)
    assert len(scores) == 1
    assert scores[0].asset_type == AssetType.STOCK


def test_engine_custom_strategies_injection() -> None:
    """Verifies dependency injection of custom strategy
    mapping in PortfolioOpportunityEngine."""
    dummy_strategy: ScoringStrategy = EtfScoringStrategy()
    custom_strategies: dict[AssetType, ScoringStrategy] = {
        AssetType.ETF: dummy_strategy,
    }
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine(
        strategies=custom_strategies
    )

    assets_data: list[dict[str, Any]] = [
        {
            "symbol": "ETF_ONLY",
            "asset_type": "ETF",
            "current_price": 100.0,
            "peak_price": 100.0,
            "target_allocation_pct": 10.0,
            "current_allocation_pct": 5.0,
        }
    ]

    scores: list[AssetScore] = engine.rank_assets(assets_data)
    assert len(scores) == 1


def test_engine_raises_error_on_missing_required_key() -> None:
    """Verifies that engine raises KeyError with missing field
    list and symbol when mandatory keys are missing."""
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()

    invalid_asset: list[dict[str, Any]] = [
        {
            "symbol": "MISSING_KEYS_ASSET",
            "asset_type": "STOCK",
            "current_price": 100.0,
        }
    ]

    with pytest.raises(KeyError, match="MISSING_KEYS_ASSET") as exc_info:
        engine.rank_assets(invalid_asset)

    assert "missing required fields" in str(exc_info.value)


def test_engine_raises_error_on_missing_symbol_and_required_keys() -> None:
    """Verifies default symbol 'UNKNOWN' when symbol key is missing."""
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()

    invalid_asset: list[dict[str, Any]] = [
        {
            "asset_type": "STOCK",
            "current_price": 100.0,
        }
    ]

    with pytest.raises(KeyError, match="UNKNOWN"):
        engine.rank_assets(invalid_asset)


def test_engine_raises_error_on_invalid_asset_type() -> None:
    """Verifies that engine raises ValueError when encountering
    an unknown asset_type string."""
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine()

    invalid_asset: list[dict[str, Any]] = [
        {
            "symbol": "CRYPTO",
            "asset_type": "BITCOIN",
            "current_price": 50000.0,
            "peak_price": 60000.0,
            "target_allocation_pct": 5.0,
            "current_allocation_pct": 0.0,
        }
    ]

    with pytest.raises(ValueError, match="Unsupported or missing asset_type 'BITCOIN'"):
        engine.rank_assets(invalid_asset)


def test_engine_raises_error_on_unregistered_asset_type() -> None:
    """Verifies ValueError when valid AssetType enum is
    not registered in strategy dict."""
    custom_strategies: dict[AssetType, ScoringStrategy] = {
        AssetType.ETF: EtfScoringStrategy(),
    }
    engine: PortfolioOpportunityEngine = PortfolioOpportunityEngine(
        strategies=custom_strategies
    )

    unregistered_stock_asset: list[dict[str, Any]] = [
        {
            "symbol": "AAPL",
            "asset_type": "STOCK",
            "current_price": 180.0,
            "peak_price": 200.0,
            "target_allocation_pct": 15.0,
            "current_allocation_pct": 5.0,
        }
    ]

    with pytest.raises(
        ValueError, match="No strategy registered for asset_type 'STOCK'"
    ):
        engine.rank_assets(unregistered_stock_asset)
