"""Unit tests for CLI opportunity module in src/cli/opportunity.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.opportunity import (
    _display_rebalance_results,
    _format_action,
    _format_urgency,
    app,
    calculate_current_allocations,
    enrich_target_asset,
    export_outputs,
)
from src.core.exceptions import (
    GeminiQuotaError,
)
from src.core.models import (
    CountryExposure,
    ETFDetails,
    Holding,
    Quotation,
    RebalanceRecommendation,
    RecommendationAction,
    SectorExposure,
    StockDetails,
    UrgencyLevel,
)
from src.core.opportunity_evaluation.base import AssetScore, AssetType

runner: CliRunner = CliRunner()


def test_calculate_current_allocations_success() -> None:
    """Validates real allocation % and total value calculation."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_stock_provider.get_price.side_effect = [
        Quotation(price=100.0, currency="EUR"),
        Quotation(price=200.0, currency="EUR"),
    ]

    portfolio_items: list[dict[str, Any]] = [
        {"yahoo_ticker": "AAPL", "quantity": 2.0, "asset_type": "STOCK"},
        {"yahoo_ticker": "MSFT", "quantity": 1.0, "asset_type": "STOCK"},
    ]

    allocations: dict[str, float]
    total_val: float
    allocations, total_val = calculate_current_allocations(
        portfolio_items, mock_stock_provider
    )

    assert total_val == 400.0
    assert allocations["AAPL"] == 50.0
    assert allocations["MSFT"] == 50.0


def test_calculate_current_allocations_skips_invalid_items() -> None:
    """Validates calculate_current_allocations skips unpriced items."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_stock_provider.get_price.return_value = Quotation(price=0.0, currency="EUR")

    portfolio_items: list[dict[str, Any]] = [
        {"quantity": 0.0},
        {"yahoo_ticker": "AAPL", "quantity": 1.0},
    ]

    allocations: dict[str, float]
    total_val: float
    allocations, total_val = calculate_current_allocations(
        portfolio_items, mock_stock_provider
    )

    assert total_val == 0.0
    assert allocations == {}


def test_enrich_target_asset_missing_symbol_raises_value_error() -> None:
    """Validates enrich_target_asset raises ValueError when symbol missing."""
    mock_stock: MagicMock = MagicMock()
    mock_etf: MagicMock = MagicMock()

    with pytest.raises(ValueError, match="Missing symbol or type"):
        enrich_target_asset({}, 0.0, mock_stock, mock_etf)


def test_enrich_target_asset_stock() -> None:
    """Validates target enrichment for STOCK assets fetching live details."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_etf_provider: MagicMock = MagicMock()

    mock_stock_provider.get_price.return_value = Quotation(price=150.0, currency="EUR")
    mock_stock_provider.get_details.return_value = StockDetails(
        fifty_two_week_high=200.0,
        fifty_two_week_low=100.0,
        pe_ratio=25.0,
        forward_pe=20.0,
    )

    target: dict[str, Any] = {
        "yahoo_ticker": "AAPL",
        "asset_type": "STOCK",
        "target_allocation_pct": 15.0,
    }

    enriched: dict[str, Any] = enrich_target_asset(
        target=target,
        current_alloc_pct=10.0,
        stock_provider=mock_stock_provider,
        etf_provider=mock_etf_provider,
    )

    assert enriched["symbol"] == "AAPL"
    assert enriched["asset_type"] == "STOCK"
    assert enriched["current_price"] == 150.0
    assert enriched["peak_price"] == 200.0
    assert enriched["trailing_pe"] == 25.0
    assert enriched["forward_pe"] == 20.0
    assert enriched["ter"] is None


def test_enrich_target_asset_price_zero_fallback() -> None:
    """Validates peak price calculation when current price is zero."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_etf_provider: MagicMock = MagicMock()

    mock_stock_provider.get_price.return_value = Quotation(price=0.0, currency="EUR")
    mock_stock_provider.get_details.return_value = None

    target: dict[str, Any] = {
        "yahoo_ticker": "UNKNOWN",
        "asset_type": "STOCK",
        "target_allocation_pct": 5.0,
    }

    enriched: dict[str, Any] = enrich_target_asset(
        target=target,
        current_alloc_pct=0.0,
        stock_provider=mock_stock_provider,
        etf_provider=mock_etf_provider,
    )

    assert enriched["current_price"] == 0.0
    assert enriched["peak_price"] == 0.01
    assert enriched["country"] == "United States"


def test_enrich_target_asset_etf() -> None:
    """Validates target enrichment for ETF assets fetching TER/breakdowns."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_etf_provider: MagicMock = MagicMock()

    mock_stock_provider.get_price.return_value = Quotation(price=100.0, currency="EUR")
    mock_stock_provider.get_details.return_value = None
    mock_etf_provider.get_details.return_value = ETFDetails(
        holdings=[Holding(name="Apple", isin="US1", ticker="AAPL", weight_pct=5.0)],
        sector_breakdown=[SectorExposure(sector_name="Tech", weight_pct=50.0)],
        country_breakdown=[CountryExposure(country_name="US", weight_pct=100.0)],
        ter_pct=0.20,
    )

    target: dict[str, Any] = {
        "yahoo_ticker": "EUNL.DE",
        "asset_type": "ETF",
        "target_allocation_pct": 20.0,
    }

    enriched: dict[str, Any] = enrich_target_asset(
        target=target,
        current_alloc_pct=5.0,
        stock_provider=mock_stock_provider,
        etf_provider=mock_etf_provider,
    )

    assert enriched["symbol"] == "EUNL.DE"
    assert enriched["asset_type"] == "ETF"
    assert enriched["ter"] == 0.20
    assert len(enriched["sector_breakdown"]) == 1
    assert len(enriched["country_breakdown"]) == 1
    assert len(enriched["top_holdings"]) == 1


def test_format_action_and_urgency() -> None:
    """Validates color-coded formatting for actions and urgency levels."""
    assert "BUY" in _format_action(RecommendationAction.BUY).plain
    assert "SELL" in _format_action(RecommendationAction.SELL).plain
    assert "HOLD" in _format_action(RecommendationAction.HOLD).plain
    assert "N/A" in _format_action(None).plain

    assert "HIGH" in _format_urgency(UrgencyLevel.HIGH).plain
    assert "MED" in _format_urgency(UrgencyLevel.MEDIUM).plain
    assert "LOW" in _format_urgency(UrgencyLevel.LOW).plain
    assert "N/A" in _format_urgency(None).plain


def test_export_outputs_success(tmp_path: Path) -> None:
    """Validates export_outputs writes CSV matrix and HTML report."""
    score: AssetScore = AssetScore(
        symbol="AAPL",
        asset_type=AssetType.STOCK,
        dip_score=0.8,
        cost_score=0.9,
        allocation_score=0.7,
        total_score=0.82,
    )

    asset_dict: dict[str, dict[str, Any]] = {
        "AAPL": {
            "current_price": 150.0,
            "current_allocation_pct": 10.0,
            "target_allocation_pct": 15.0,
        }
    }

    rec: RebalanceRecommendation = RebalanceRecommendation(
        action=RecommendationAction.BUY,
        confidence_score=0.95,
        reasoning="Good valuation dip.",
        target_allocation_pct=15.0,
        urgency_level=UrgencyLevel.HIGH,
        risk_score=2,
        valuation_score=8,
    )

    export_outputs(
        ranked_scores=[score],
        asset_dict_map=asset_dict,
        recommendations_map={"AAPL": rec},
        total_val=1000.0,
        has_ai=True,
        output_dir=tmp_path,
    )

    csv_path: Path = tmp_path / "tables/opportunity_output.csv"
    html_path: Path = tmp_path / "reports/opportunity_report.html"

    assert csv_path.exists()
    assert html_path.exists()

    with open(csv_path, encoding="utf-8") as file:
        reader: list[dict[str, str]] = list(csv.DictReader(file))
        assert len(reader) == 1
        assert reader[0]["symbol"] == "AAPL"
        assert reader[0]["ai_action"] == "BUY"


def test_export_outputs_etf_html_contains_ticker(tmp_path: Path) -> None:
    """Validates export_outputs renders ETF details into the HTML report."""
    score: AssetScore = AssetScore(
        symbol="EUNL.DE",
        asset_type=AssetType.ETF,
        dip_score=0.5,
        cost_score=0.6,
        allocation_score=0.7,
        total_score=0.60,
    )

    asset_dict: dict[str, dict[str, Any]] = {
        "EUNL.DE": {
            "asset_type": "ETF",
            "current_price": 80.0,
            "peak_price": 85.0,
            "current_allocation_pct": 5.0,
            "target_allocation_pct": 10.0,
            "ter": 0.20,
            "top_holdings": [{"name": "Apple", "weight_pct": 5.0}],
            "sector_breakdown": [{"sector_name": "Tech", "weight_pct": 50.0}],
            "country_breakdown": [{"country_name": "USA", "weight_pct": 70.0}],
        }
    }

    rec: RebalanceRecommendation = RebalanceRecommendation(
        action=RecommendationAction.BUY,
        confidence_score=0.85,
        reasoning="Broad ETF rebalance.",
        target_allocation_pct=10.0,
        urgency_level=UrgencyLevel.MEDIUM,
        risk_score=1,
        valuation_score=7,
    )

    export_outputs(
        ranked_scores=[score],
        asset_dict_map=asset_dict,
        recommendations_map={"EUNL.DE": rec},
        total_val=2000.0,
        has_ai=True,
        output_dir=tmp_path,
    )

    html_path: Path = tmp_path / "reports/opportunity_report.html"
    assert html_path.exists()
    content: str = html_path.read_text(encoding="utf-8")
    assert "EUNL.DE" in content


def test_export_outputs_render_error_does_not_raise(tmp_path: Path) -> None:
    """export_outputs handles HTML render failure gracefully (no crash)."""
    score: AssetScore = AssetScore(
        symbol="AAPL",
        asset_type=AssetType.STOCK,
        dip_score=0.8,
        cost_score=0.9,
        allocation_score=0.7,
        total_score=0.82,
    )

    asset_dict: dict[str, dict[str, Any]] = {
        "AAPL": {
            "current_price": 150.0,
            "current_allocation_pct": 10.0,
            "target_allocation_pct": 15.0,
        }
    }

    with patch("src.utils.render.render_html", side_effect=RuntimeError("render fail")):
        export_outputs(
            ranked_scores=[score],
            asset_dict_map=asset_dict,
            recommendations_map={},
            total_val=1000.0,
            has_ai=False,
            output_dir=tmp_path,
        )


def test_export_outputs_error_handling(tmp_path: Path) -> None:
    """Validates export_outputs handles permission/path failure gracefully."""
    invalid_path: Path = tmp_path / "non_existent_folder" / "sub"
    with patch("builtins.open", side_effect=OSError("Disk full")):
        export_outputs([], {}, {}, 1000.0, False, output_dir=invalid_path)


def test_display_rebalance_results_rendering() -> None:
    """Validates _display_rebalance_results renders tables and cards."""
    score_stock: AssetScore = AssetScore(
        symbol="AAPL",
        asset_type=AssetType.STOCK,
        dip_score=0.8,
        cost_score=0.9,
        allocation_score=0.7,
        total_score=0.82,
    )

    asset_dict: dict[str, dict[str, Any]] = {
        "AAPL": {
            "asset_type": "STOCK",
            "current_price": 150.0,
            "peak_price": 200.0,
            "low_52w": 120.0,
            "current_allocation_pct": 10.0,
            "target_allocation_pct": 15.0,
            "trailing_pe": 25.0,
            "forward_pe": 20.0,
        },
    }

    rec: RebalanceRecommendation = RebalanceRecommendation(
        action=RecommendationAction.BUY,
        confidence_score=0.90,
        reasoning="Solid buy opportunity.",
        target_allocation_pct=15.0,
        urgency_level=UrgencyLevel.HIGH,
        risk_score=2,
        valuation_score=8,
    )

    _display_rebalance_results(
        ranked_scores=[score_stock],
        asset_dict_map=asset_dict,
        recommendations_map={"AAPL": rec},
        total_val=1000.0,
        has_ai=True,
        verbose=True,
    )


def test_display_rebalance_results_sell_action_and_missing_rec() -> None:
    """Validates _display_rebalance_results with SELL action and missing rec."""
    score_sell: AssetScore = AssetScore(
        symbol="TSLA",
        asset_type=AssetType.STOCK,
        dip_score=0.2,
        cost_score=0.3,
        allocation_score=0.1,
        total_score=0.20,
    )
    score_missing: AssetScore = AssetScore(
        symbol="MSFT",
        asset_type=AssetType.STOCK,
        dip_score=0.5,
        cost_score=0.5,
        allocation_score=0.5,
        total_score=0.50,
    )

    asset_dict: dict[str, dict[str, Any]] = {
        "TSLA": {
            "asset_type": "STOCK",
            "current_price": 250.0,
            "peak_price": 300.0,
            "current_allocation_pct": 20.0,
            "target_allocation_pct": 10.0,
        },
        "MSFT": {
            "asset_type": "STOCK",
            "current_price": 400.0,
            "current_allocation_pct": 10.0,
            "target_allocation_pct": 10.0,
        },
    }

    rec_sell: RebalanceRecommendation = RebalanceRecommendation(
        action=RecommendationAction.SELL,
        confidence_score=0.80,
        reasoning="Overvalued position.",
        target_allocation_pct=10.0,
        urgency_level=UrgencyLevel.HIGH,
        risk_score=4,
        valuation_score=3,
    )

    _display_rebalance_results(
        ranked_scores=[score_sell, score_missing],
        asset_dict_map=asset_dict,
        recommendations_map={"TSLA": rec_sell},
        total_val=5000.0,
        has_ai=True,
        verbose=False,
    )


def test_rebalance_command_missing_targets(tmp_path: Path) -> None:
    """Validates CLI exits with non-zero code when target file is empty."""
    targets: Path = tmp_path / "empty_targets.json"
    portfolio: Path = tmp_path / "portfolio.json"
    targets.write_text("[]", encoding="utf-8")
    portfolio.write_text("[]", encoding="utf-8")

    result: Any = runner.invoke(
        app,
        [
            "--targets-file",
            str(targets),
            "--portfolio-file",
            str(portfolio),
        ],
    )

    assert result.exit_code != 0


@patch("src.cli.opportunity.calculate_current_allocations")
@patch("src.cli.opportunity.enrich_target_asset")
@patch("src.cli.opportunity.GeminiClient")
def test_rebalance_command_full_success(
    mock_gemini_cls: MagicMock,
    mock_enrich: MagicMock,
    mock_calc: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates full execution of rebalance command including AI."""
    targets: Path = tmp_path / "targets.json"
    portfolio: Path = tmp_path / "portfolio.json"

    targets.write_text(
        '[{"yahoo_ticker": "AAPL", "asset_type": "STOCK"}]',
        encoding="utf-8",
    )
    portfolio.write_text(
        '[{"yahoo_ticker": "AAPL", "quantity": 1.0}]', encoding="utf-8"
    )

    mock_calc.return_value = ({"AAPL": 100.0}, 150.0)
    mock_enrich.return_value = {
        "symbol": "AAPL",
        "asset_type": "STOCK",
        "current_price": 150.0,
        "peak_price": 180.0,
        "target_allocation_pct": 100.0,
        "current_allocation_pct": 100.0,
        "ter": None,
        "trailing_pe": 25.0,
        "forward_pe": 20.0,
        "low_52w": 120.0,
        "high_52w": 180.0,
        "sector_breakdown": [],
        "country_breakdown": [],
        "top_holdings": [],
    }

    mock_instance: MagicMock = MagicMock()
    mock_instance.analyze_portfolio_batch.return_value = {}
    mock_gemini_cls.return_value = mock_instance

    result: Any = runner.invoke(
        app,
        [
            "--targets-file",
            str(targets),
            "--portfolio-file",
            str(portfolio),
            "--verbose",
        ],
    )

    assert result.exit_code == 0


@patch("src.cli.opportunity.calculate_current_allocations")
@patch("src.cli.opportunity.enrich_target_asset")
@patch("src.cli.opportunity.SqliteOpportunityRepository")
def test_rebalance_command_partial_enrichment_and_db_save(
    mock_opp_repo_cls: MagicMock,
    mock_enrich: MagicMock,
    mock_calc: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates partial asset enrichment error handling and SQLite save."""
    targets: Path = tmp_path / "targets.json"
    portfolio: Path = tmp_path / "portfolio.json"

    targets.write_text(
        "["
        '{"yahoo_ticker": "AAPL", "asset_type": "STOCK"},'
        '{"yahoo_ticker": "FAIL", "asset_type": "STOCK"}'
        "]",
        encoding="utf-8",
    )
    portfolio.write_text("[]", encoding="utf-8")

    mock_calc.return_value = ({}, 150.0)

    def side_effect_enrich(
        target: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        sym: str = target.get("yahoo_ticker", "")
        if sym == "FAIL":
            raise ValueError("Enrichment error")
        return {
            "symbol": "AAPL",
            "asset_type": "STOCK",
            "current_price": 150.0,
            "peak_price": 180.0,
            "target_allocation_pct": 100.0,
            "current_allocation_pct": 0.0,
            "ter": None,
            "trailing_pe": 25.0,
            "forward_pe": 20.0,
            "low_52w": 120.0,
            "high_52w": 180.0,
            "sector_breakdown": [],
            "country_breakdown": [],
            "top_holdings": [],
        }

    mock_enrich.side_effect = side_effect_enrich

    mock_repo: MagicMock = MagicMock()
    mock_opp_repo_cls.return_value = mock_repo
    mock_repo.load_asset_history.return_value = []

    with patch.dict("sys.modules"):
        sys.modules.pop("pytest", None)
        result: Any = runner.invoke(
            app,
            [
                "--targets-file",
                str(targets),
                "--portfolio-file",
                str(portfolio),
                "--skip-ai",
            ],
        )

    assert result.exit_code == 0
    mock_repo.save_opportunity_report.assert_called_once()


@patch("src.cli.opportunity.calculate_current_allocations")
@patch("src.cli.opportunity.enrich_target_asset")
@patch("src.cli.opportunity.SqliteOpportunityRepository")
def test_rebalance_command_db_save_failure(
    mock_opp_repo_cls: MagicMock,
    mock_enrich: MagicMock,
    mock_calc: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates rebalance command handling database saving failure."""
    targets: Path = tmp_path / "targets.json"
    portfolio: Path = tmp_path / "portfolio.json"

    targets.write_text(
        '[{"yahoo_ticker": "AAPL", "asset_type": "STOCK"}]',
        encoding="utf-8",
    )
    portfolio.write_text("[]", encoding="utf-8")

    mock_calc.return_value = ({}, 150.0)
    mock_enrich.return_value = {
        "symbol": "AAPL",
        "asset_type": "STOCK",
        "current_price": 150.0,
        "peak_price": 180.0,
        "target_allocation_pct": 100.0,
        "current_allocation_pct": 0.0,
        "ter": None,
        "trailing_pe": 25.0,
        "forward_pe": 20.0,
        "low_52w": 120.0,
        "high_52w": 180.0,
        "sector_breakdown": [],
        "country_breakdown": [],
        "top_holdings": [],
    }

    mock_repo: MagicMock = MagicMock()
    mock_opp_repo_cls.return_value = mock_repo
    mock_repo.save_opportunity_report.side_effect = RuntimeError("DB write error")

    with patch.dict("sys.modules"):
        sys.modules.pop("pytest", None)
        result: Any = runner.invoke(
            app,
            [
                "--targets-file",
                str(targets),
                "--portfolio-file",
                str(portfolio),
                "--skip-ai",
            ],
        )

    assert result.exit_code == 0


@patch("src.cli.opportunity.calculate_current_allocations")
@patch("src.cli.opportunity.enrich_target_asset")
@patch("src.cli.opportunity.GeminiClient")
def test_rebalance_command_gemini_quota_error_fallback(
    mock_gemini_cls: MagicMock,
    mock_enrich: MagicMock,
    mock_calc: MagicMock,
    tmp_path: Path,
) -> None:
    """Validates rebalance command falls back when Gemini quota is exceeded."""
    targets: Path = tmp_path / "targets.json"
    portfolio: Path = tmp_path / "portfolio.json"

    targets.write_text(
        '[{"yahoo_ticker": "AAPL", "asset_type": "STOCK"}]',
        encoding="utf-8",
    )
    portfolio.write_text("[]", encoding="utf-8")

    mock_calc.return_value = ({}, 150.0)
    mock_enrich.return_value = {
        "symbol": "AAPL",
        "asset_type": "STOCK",
        "current_price": 150.0,
        "peak_price": 180.0,
        "target_allocation_pct": 100.0,
        "current_allocation_pct": 0.0,
        "ter": None,
        "trailing_pe": 25.0,
        "forward_pe": 20.0,
        "low_52w": 120.0,
        "high_52w": 180.0,
        "sector_breakdown": [],
        "country_breakdown": [],
        "top_holdings": [],
    }

    mock_instance: MagicMock = MagicMock()
    mock_instance.analyze_portfolio_batch.side_effect = GeminiQuotaError(
        "Quota exceeded"
    )
    mock_gemini_cls.return_value = mock_instance

    result: Any = runner.invoke(
        app,
        [
            "--targets-file",
            str(targets),
            "--portfolio-file",
            str(portfolio),
        ],
    )

    assert result.exit_code == 0
