"""Unit tests for src/cli/quality.py."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer

from src.cli.quality import (
    _format_tier,
    analyze_quality_cmd,
    export_quality_report,
    save_quality_to_database,
)
from src.core.exceptions import StorageError
from src.core.models import (
    Asset,
    CountryExposure,
    ETFDetails,
    Holding,
    SectorExposure,
    StockDetails,
)
from src.infra.database.schema import initialize_database

# ==============================================================================
# Helpers
# ==============================================================================


def _make_asset(
    name: str = "Apple",
    isin: str = "US0378331005",
    ticker: str = "AAPL",
    asset_type: str = "STOCK",
) -> Asset:
    return Asset(
        name=name,
        isin=isin,
        yahoo_ticker=ticker,
        asset_type=asset_type,
        quantity=1.0,
        average_buy_price=100.0,
    )


def _make_etf_asset() -> Asset:
    return _make_asset(
        name="World ETF",
        isin="IE00B4L5Y983",
        ticker="EUNL.DE",
        asset_type="ETF",
    )


def _make_stock_details(**kwargs: Any) -> StockDetails:
    defaults: dict[str, Any] = {
        "pe_ratio": 20.0,
        "forward_pe": 18.0,
        "peg_ratio": 1.5,
        "price_to_book": 3.0,
        "dividend_yield_pct": 1.5,
        "beta": 1.1,
        "profit_margins_pct": 22.0,
        "revenue_growth_pct": 8.0,
        "earnings_growth_pct": 12.0,
        "total_debt_to_equity": 60.0,
        "fifty_two_week_high": 200.0,
        "fifty_two_week_low": 120.0,
        "market_cap": 2_000_000_000.0,
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }
    defaults.update(kwargs)
    return StockDetails(**defaults)


def _make_etf_details(ter: float | None = 0.20) -> ETFDetails:
    return ETFDetails(
        ter_pct=ter,
        holdings=[
            Holding(name="Apple", isin="US0378331005", ticker="AAPL", weight_pct=5.5)
        ],
        sector_breakdown=[SectorExposure(sector_name="Technology", weight_pct=30.0)],
        country_breakdown=[CountryExposure(country_name="USA", weight_pct=60.0)],
    )


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    initialize_database(conn)
    conn.close()
    return db


def _make_targets_file(tmp_path: Path, assets: list[Asset]) -> Path:
    """Creates a temporary portfolio_targets.json from a list of Assets."""
    data = {
        "assets": [
            {
                "name": a.name,
                "isin": a.isin,
                "yahoo_ticker": a.yahoo_ticker,
                "asset_type": a.asset_type,
            }
            for a in assets
        ]
    }
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps(data), encoding="utf-8")
    return targets


# ==============================================================================
# _format_tier
# ==============================================================================


def test_format_tier_a_returns_green() -> None:
    """Tier A string produces bold green Rich Text."""
    result = _format_tier("Tier A")
    assert result.style == "bold green"
    assert result.plain == "Tier A"


def test_format_tier_b_returns_yellow() -> None:
    """Tier B string produces bold yellow Rich Text."""
    result = _format_tier("Tier B")
    assert result.style == "bold yellow"


def test_format_tier_c_returns_red() -> None:
    """Anything else (Tier C / unknown) produces bold red Rich Text."""
    result = _format_tier("Tier C")
    assert result.style == "bold red"


def test_format_tier_lowercase_a() -> None:
    """Lowercase 'tier a' is matched case-insensitively."""
    result = _format_tier("tier a — excellent")
    assert result.style == "bold green"


def test_format_tier_unknown_returns_red() -> None:
    """Unrecognised tier defaults to bold red."""
    result = _format_tier("Unknown")
    assert result.style == "bold red"


# ==============================================================================
# export_quality_report
# ==============================================================================


def _stock_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": "Apple",
        "symbol": "AAPL",
        "asset_type": "STOCK",
        "tier": "Tier A",
        "score": 90,
        "valuation_status": "Fair Value",
        "tr_str": "20.0",
        "fw_str": "18.0",
        "peg_str": "1.50",
        "pb_str": "3.00",
        "div_str": "1.50%",
        "beta_str": "1.10",
        "margin_str": "22.0%",
        "rev_str": "8.0%",
        "earn_str": "12.0%",
        "debt_str": "60.0",
        "low_str": "120.00 EUR",
        "peak_str": "200.00 EUR",
        "bull_case": ["Strong margins", "Revenue growing"],
        "bear_case": ["Valuation stretched"],
    }
    item.update(overrides)
    return item


def _etf_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": "World ETF",
        "symbol": "EUNL.DE",
        "asset_type": "ETF",
        "tier": "Tier A",
        "score": 100,
        "valuation_status": "Fair Value",
        "ter_str": "0.20%",
        "holdings_str": "Apple (5.5%)",
        "sectors_str": "Technology (30.0%)",
        "countries_str": "USA (60.0%)",
        "bull_case": ["Low TER"],
        "bear_case": ["Concentration risk"],
    }
    item.update(overrides)
    return item


def test_export_quality_report_creates_html(tmp_path: Path) -> None:
    """HTML file is created with expected content."""
    with patch("src.utils.render.render_html") as mock_render:
        export_quality_report([_stock_item()], output_dir=tmp_path)
    mock_render.assert_called_once()
    args = mock_render.call_args[0]
    assert args[0] == "quality_report.html.j2"
    assert args[2] == tmp_path / "quality_report.html"


def test_export_quality_report_passes_assets_to_template(tmp_path: Path) -> None:
    """Template context contains the evaluated assets list."""
    with patch("src.utils.render.render_html") as mock_render:
        export_quality_report([_stock_item(), _etf_item()], output_dir=tmp_path)
    ctx = mock_render.call_args[0][1]
    assert len(ctx["assets"]) == 2


def test_export_quality_report_empty_list(tmp_path: Path) -> None:
    """render_html is still called with an empty assets list."""
    with patch("src.utils.render.render_html") as mock_render:
        export_quality_report([], output_dir=tmp_path)
    ctx = mock_render.call_args[0][1]
    assert ctx["assets"] == []


def test_export_quality_report_generated_at_present(tmp_path: Path) -> None:
    """Template context includes a generated_at timestamp string."""
    with patch("src.utils.render.render_html") as mock_render:
        export_quality_report([_stock_item()], output_dir=tmp_path)
    ctx = mock_render.call_args[0][1]
    assert "generated_at" in ctx
    assert len(ctx["generated_at"]) > 0


@patch("src.cli.quality.logger")
def test_export_quality_report_render_error_logged(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Error is logged when render_html raises."""
    with patch("src.utils.render.render_html", side_effect=RuntimeError("render fail")):
        export_quality_report([_stock_item()], output_dir=tmp_path)
    mock_logger.error.assert_called_once()
    assert "Failed to export" in mock_logger.error.call_args[0][0]


# ==============================================================================
# save_quality_to_database
# ==============================================================================


@patch("src.cli.quality.logger")
def test_save_quality_db_not_found_logs_warning(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Validates warning when database file does not exist."""
    missing_db = tmp_path / "nonexistent.db"
    save_quality_to_database([_stock_item()], db_path=missing_db)
    mock_logger.warning.assert_called_once()
    assert "not found" in mock_logger.warning.call_args[0][0]


def test_save_quality_db_stock_asset_inserted(tmp_path: Path) -> None:
    """Validates stock asset and history row inserted when asset missing."""
    db = _make_db(tmp_path)
    save_quality_to_database([_stock_item()], db_path=db)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT quality_tier, quality_score FROM stock_fundamental_history"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Tier A"
    assert rows[0][1] == 90


def test_save_quality_db_stock_asset_existing(tmp_path: Path) -> None:
    """Validates history row uses existing asset id when asset already exists."""
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO assets (isin, name, yahoo_ticker, quantity,"
        " average_buy_price, asset_type) VALUES (?,?,?,0,0,?)",
        ("US0378331005", "Apple", "AAPL", "STOCK"),
    )
    conn.commit()
    existing_id = conn.execute(
        "SELECT id FROM assets WHERE yahoo_ticker='AAPL'"
    ).fetchone()[0]
    conn.close()

    save_quality_to_database([_stock_item()], db_path=db)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT asset_id FROM stock_fundamental_history").fetchall()
    conn.close()
    assert rows[0][0] == existing_id


def test_save_quality_db_etf_asset_inserted(tmp_path: Path) -> None:
    """Validates ETF asset inserts into etf_fundamental_history."""
    db = _make_db(tmp_path)
    save_quality_to_database([_etf_item()], db_path=db)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT quality_tier, quality_score FROM etf_fundamental_history"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Tier A"
    assert rows[0][1] == 100


def test_save_quality_db_etf_with_details(tmp_path: Path) -> None:
    """Validates ETF details (TER, holdings, sectors, countries) are persisted."""
    db = _make_db(tmp_path)
    item = _etf_item()
    item["etf_details"] = _make_etf_details(ter=0.15)
    save_quality_to_database([item], db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ter_pct, holdings_json FROM etf_fundamental_history"
    ).fetchone()
    conn.close()
    assert row[0] == pytest.approx(0.15)
    assert "Apple" in row[1]


def test_save_quality_db_etf_details_none(tmp_path: Path) -> None:
    """Validates ETF row saved with NULLs when etf_details is None."""
    db = _make_db(tmp_path)
    item = _etf_item()
    item["etf_details"] = None
    save_quality_to_database([item], db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ter_pct, holdings_json FROM etf_fundamental_history"
    ).fetchone()
    conn.close()
    assert row[0] is None
    assert row[1] == "[]"


def test_save_quality_db_stock_details_none(tmp_path: Path) -> None:
    """Validates stock row saved with NULLs when stock_details is None."""
    db = _make_db(tmp_path)
    item = _stock_item()
    item["stock_details"] = None
    save_quality_to_database([item], db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT market_cap, pe_ratio FROM stock_fundamental_history"
    ).fetchone()
    conn.close()
    assert row[0] is None
    assert row[1] is None


def test_save_quality_db_score_non_int_defaults_to_zero(tmp_path: Path) -> None:
    """Validates non-integer score is coerced to 0."""
    db = _make_db(tmp_path)
    item = _stock_item(score="bad_value")
    save_quality_to_database([item], db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT quality_score FROM stock_fundamental_history").fetchone()
    conn.close()
    assert row[0] == 0


def test_save_quality_db_stock_with_full_details(tmp_path: Path) -> None:
    """Validates all stock fundamental fields are persisted."""
    db = _make_db(tmp_path)
    item = _stock_item()
    item["stock_details"] = _make_stock_details()
    save_quality_to_database([item], db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT market_cap, sector, industry FROM stock_fundamental_history"
    ).fetchone()
    conn.close()
    assert row[1] == "Technology"
    assert row[2] == "Consumer Electronics"


@patch("src.cli.quality.logger")
def test_save_quality_db_exception_logged(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Validates exception during DB write is caught and logged."""
    db = _make_db(tmp_path)
    with patch("src.cli.quality.sqlite3.connect", side_effect=RuntimeError("fail")):
        save_quality_to_database([_stock_item()], db_path=db)
    mock_logger.error.assert_called_once()
    assert "Failed to persist" in mock_logger.error.call_args[0][0]


# ==============================================================================
# analyze_quality_cmd
# ==============================================================================


@patch("src.cli.quality.logger")
def test_analyze_quality_cmd_storage_error_exits(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Validates Exit(code=1) when portfolio load raises StorageError."""
    mock_repo = MagicMock()
    mock_repo.load_assets.side_effect = StorageError("db error")
    missing = tmp_path / "missing.json"
    with patch("src.cli.quality.SqlitePortfolioRepository", return_value=mock_repo):
        with pytest.raises(typer.Exit) as exc:
            analyze_quality_cmd(ticker=None, targets_file=missing)
    assert exc.value.exit_code == 1
    mock_logger.error.assert_called_once()


@patch("src.cli.quality.logger")
def test_analyze_quality_cmd_no_assets_warns(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Validates exit when targets file contains empty assets list."""
    empty_targets = tmp_path / "empty.json"
    empty_targets.write_text('{"assets": []}', encoding="utf-8")
    with pytest.raises(typer.Exit) as exc:
        analyze_quality_cmd(ticker=None, targets_file=empty_targets)
    assert exc.value.exit_code == 1
    mock_logger.error.assert_called_once()


def test_analyze_quality_cmd_ticker_not_found_exits(tmp_path: Path) -> None:
    """Validates Exit(code=1) when specified ticker is absent from portfolio."""
    targets = _make_targets_file(tmp_path, [_make_asset()])
    with (
        patch("src.cli.quality.StockProvider"),
        patch("src.cli.quality.ETFProvider"),
    ):
        with pytest.raises(typer.Exit) as exc:
            analyze_quality_cmd(ticker="NONEXISTENT", targets_file=targets)
    assert exc.value.exit_code == 1


def test_analyze_quality_cmd_stock_with_details(tmp_path: Path) -> None:
    """Validates full stock path runs without errors."""
    assets = [_make_asset()]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(
                get_details=MagicMock(return_value=_make_stock_details())
            ),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database") as mock_save,
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    mock_export.assert_called_once()
    mock_save.assert_called_once()


def test_analyze_quality_cmd_stock_no_details(tmp_path: Path) -> None:
    """Validates fallback diagnostic when stock provider returns None."""
    assets = [_make_asset()]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=None)),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["tier"] == "Tier C"
    assert items[0]["score"] == 0


def test_analyze_quality_cmd_etf_with_details(tmp_path: Path) -> None:
    """Validates full ETF path runs without errors."""
    assets = [_make_etf_asset()]
    targets = _make_targets_file(tmp_path, assets)
    etf_details = _make_etf_details()
    with (
        patch("src.cli.quality.StockProvider"),
        patch(
            "src.cli.quality.ETFProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=etf_details)),
        ),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database") as mock_save,
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    mock_export.assert_called_once()
    mock_save.assert_called_once()
    items = mock_export.call_args[0][0]
    assert items[0]["asset_type"] == "ETF"
    assert "ter_str" in items[0]


def test_analyze_quality_cmd_etf_no_details(tmp_path: Path) -> None:
    """Validates fallback diagnostic when ETF provider returns None."""
    assets = [_make_etf_asset()]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch("src.cli.quality.StockProvider"),
        patch(
            "src.cli.quality.ETFProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=None)),
        ),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["tier"] == "Tier C"
    assert "ETF metadata unavailable" in items[0]["bear_case"]


def test_analyze_quality_cmd_ticker_match_by_ticker(tmp_path: Path) -> None:
    """Validates ticker filter matches by yahoo_ticker."""
    assets = [_make_asset(ticker="AAPL"), _make_asset(name="Google", ticker="GOOG")]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(
                get_details=MagicMock(return_value=_make_stock_details())
            ),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker="aapl", targets_file=targets)
    items = mock_export.call_args[0][0]
    assert len(items) == 1
    assert items[0]["symbol"] == "AAPL"


def test_analyze_quality_cmd_ticker_match_by_isin(tmp_path: Path) -> None:
    """Validates ticker filter matches by ISIN."""
    assets = [_make_asset(isin="US0378331005", ticker="AAPL")]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(
                get_details=MagicMock(return_value=_make_stock_details())
            ),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker="US0378331005", targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["symbol"] == "AAPL"


def test_analyze_quality_cmd_tier_a_border_green(tmp_path: Path) -> None:
    """Validates Tier A stock result when all quality thresholds are met."""
    assets = [_make_asset()]
    targets = _make_targets_file(tmp_path, assets)
    details = _make_stock_details(
        profit_margins_pct=25.0,
        revenue_growth_pct=10.0,
        total_debt_to_equity=50.0,
        earnings_growth_pct=15.0,
        pe_ratio=20.0,
    )
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=details)),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["tier"] == "Tier A"


def test_analyze_quality_cmd_tier_c_stock(tmp_path: Path) -> None:
    """Validates Tier C stock when knockout rules are triggered."""
    assets = [_make_asset()]
    targets = _make_targets_file(tmp_path, assets)
    details = _make_stock_details(
        profit_margins_pct=-5.0,
        revenue_growth_pct=1.0,
        total_debt_to_equity=300.0,
        earnings_growth_pct=0.0,
        pe_ratio=None,
    )
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=details)),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["tier"] == "Tier C"


def test_analyze_quality_cmd_etf_empty_holdings_sectors_countries(
    tmp_path: Path,
) -> None:
    """Validates N/A strings when ETF details have no holdings/sectors/countries."""
    assets = [_make_etf_asset()]
    targets = _make_targets_file(tmp_path, assets)
    etf_details = ETFDetails(
        ter_pct=None, holdings=[], sector_breakdown=[], country_breakdown=[]
    )
    with (
        patch("src.cli.quality.StockProvider"),
        patch(
            "src.cli.quality.ETFProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=etf_details)),
        ),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["holdings_str"] == "N/A"
    assert items[0]["sectors_str"] == "N/A"
    assert items[0]["countries_str"] == "N/A"
    assert items[0]["ter_str"] == "N/A"


def test_analyze_quality_cmd_stock_none_metrics_formatted_as_na(
    tmp_path: Path,
) -> None:
    """Validates metric strings show N/A when StockDetails fields are None."""
    assets = [_make_asset()]
    targets = _make_targets_file(tmp_path, assets)
    details = StockDetails()
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(get_details=MagicMock(return_value=details)),
        ),
        patch("src.cli.quality.ETFProvider"),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert items[0]["tr_str"] == "N/A"
    assert items[0]["fw_str"] == "N/A"
    assert items[0]["low_str"] == "N/A"
    assert items[0]["peak_str"] == "N/A"


def test_analyze_quality_cmd_multiple_assets(tmp_path: Path) -> None:
    """Validates processing loop handles multiple mixed assets."""
    assets = [_make_asset(), _make_etf_asset()]
    targets = _make_targets_file(tmp_path, assets)
    with (
        patch(
            "src.cli.quality.StockProvider",
            return_value=MagicMock(
                get_details=MagicMock(return_value=_make_stock_details())
            ),
        ),
        patch(
            "src.cli.quality.ETFProvider",
            return_value=MagicMock(
                get_details=MagicMock(return_value=_make_etf_details())
            ),
        ),
        patch("src.cli.quality.export_quality_report") as mock_export,
        patch("src.cli.quality.save_quality_to_database"),
    ):
        analyze_quality_cmd(ticker=None, targets_file=targets)
    items = mock_export.call_args[0][0]
    assert len(items) == 2
    types = {i["asset_type"] for i in items}
    assert types == {"STOCK", "ETF"}


@patch("src.cli.quality.logger")
def test_analyze_quality_cmd_invalid_targets_file_exits(
    mock_logger: MagicMock, tmp_path: Path
) -> None:
    """Validates Exit(code=1) when targets file contains invalid JSON."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not valid json", encoding="utf-8")
    with pytest.raises(typer.Exit) as exc:
        analyze_quality_cmd(ticker=None, targets_file=bad_json)
    assert exc.value.exit_code == 1
    mock_logger.error.assert_called_once()
