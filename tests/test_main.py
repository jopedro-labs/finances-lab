"""Comprehensive unit tests for main.py CLI commands using Typer CliRunner."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from main import (
    _display_single_etf_details,
    _display_single_stock_details,
    _format_market_cap,
    _pull_cloud_data,
    _push_cloud_data,
    app,
    main_callback,
)
from src.core.models import (
    Asset,
    CountryExposure,
    ETFDetails,
    ETFMarketData,
    Holding,
    PortfolioSnapshot,
    Quotation,
    SectorExposure,
    StockDetails,
)

runner: CliRunner = CliRunner()


@pytest.fixture(autouse=True)
def mock_cloud_sync_by_default() -> Generator[None]:
    """Auto-mock cloud pull and push helpers to prevent side-effects."""
    with (
        patch("main._pull_cloud_data", return_value=True),
        patch("main._push_cloud_data", return_value=True),
    ):
        yield


# --- CLOUD SYNC UNIT TESTS ---


@patch("main.GDriveService")
def test_pull_cloud_data_unit_success(mock_gdrive_cls: MagicMock) -> None:
    """Validates _pull_cloud_data unit logic when all syncs succeed."""
    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.download_file.return_value = True
    mock_service.sync_files.return_value = {"file1": True, "file2": True}

    assert _pull_cloud_data() is True


@patch("main.GDriveService")
def test_pull_cloud_data_unit_db_download_failure(
    mock_gdrive_cls: MagicMock,
) -> None:
    """Validates _pull_cloud_data returning False if DB download fails."""
    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.download_file.return_value = False
    mock_service.sync_files.return_value = {"file1": True}

    assert _pull_cloud_data() is False


@patch("main.GDriveService")
def test_pull_cloud_data_unit_config_sync_failure(
    mock_gdrive_cls: MagicMock,
) -> None:
    """Validates _pull_cloud_data returning False if config sync fails."""
    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.download_file.return_value = True
    mock_service.sync_files.return_value = {"file1": False}

    assert _pull_cloud_data() is False


@patch("main.DB_FILE")
@patch("main.CONFIG_FILES")
@patch("main.GDriveService")
def test_push_cloud_data_unit_success(
    mock_gdrive_cls: MagicMock,
    mock_configs: MagicMock,
    mock_db: MagicMock,
) -> None:
    """Validates _push_cloud_data when DB and configs exist and upload succeeds."""
    mock_db.exists.return_value = True
    mock_file: MagicMock = MagicMock()
    mock_file.exists.return_value = True
    mock_configs.__iter__.return_value = [mock_file]

    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.upload_file.return_value = True
    mock_service.sync_files.return_value = {"file1": True}

    assert _push_cloud_data() is True


@patch("main.DB_FILE")
@patch("main.CONFIG_FILES")
def test_push_cloud_data_unit_none_exist(
    mock_configs: MagicMock,
    mock_db: MagicMock,
) -> None:
    """Validates _push_cloud_data when neither DB nor configs exist."""
    mock_db.exists.return_value = False
    mock_configs.__iter__.return_value = []

    assert _push_cloud_data() is True


@patch("main.DB_FILE")
@patch("main.CONFIG_FILES")
@patch("main.GDriveService")
def test_push_cloud_data_unit_db_upload_failure(
    mock_gdrive_cls: MagicMock,
    mock_configs: MagicMock,
    mock_db: MagicMock,
) -> None:
    """Validates _push_cloud_data returning False when DB upload fails."""
    mock_db.exists.return_value = True
    mock_configs.__iter__.return_value = []

    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.upload_file.return_value = False

    assert _push_cloud_data() is False


@patch("main.DB_FILE")
@patch("main.CONFIG_FILES")
@patch("main.GDriveService")
def test_push_cloud_data_unit_config_upload_failure(
    mock_gdrive_cls: MagicMock,
    mock_configs: MagicMock,
    mock_db: MagicMock,
) -> None:
    """Validates _push_cloud_data returning False when config sync fails."""
    mock_db.exists.return_value = False
    mock_file: MagicMock = MagicMock()
    mock_file.exists.return_value = True
    mock_configs.__iter__.return_value = [mock_file]

    mock_service: MagicMock = MagicMock()
    mock_gdrive_cls.return_value = mock_service
    mock_service.sync_files.return_value = {"file1": False}

    assert _push_cloud_data() is False


# --- STARTUP CALLBACK / VALIDATION TESTS ---


def test_main_callback_success() -> None:
    """Validates normal main callback execution completes without error."""
    mock_ctx: MagicMock = MagicMock()
    mock_ctx.invoked_subcommand = "save-snapshot"
    main_callback(ctx=mock_ctx)


def test_main_callback_generic_exception_logged() -> None:
    """Validates that a generic exception during settings access is logged."""
    mock_ctx: MagicMock = MagicMock()
    mock_ctx.invoked_subcommand = "save-snapshot"
    with patch("main.logger"):
        with patch("builtins.__build_class__", side_effect=None):
            main_callback(ctx=mock_ctx)
    mock_ctx.assert_not_called()


def test_main_callback_bypass_push_pull() -> None:
    """Validates that main callback runs without errors for push-config."""
    mock_ctx: MagicMock = MagicMock()
    mock_ctx.invoked_subcommand = "push-config"
    main_callback(ctx=mock_ctx)


# --- DASHBOARD SUBCOMMAND INTEGRATION TEST ---


def test_dashboard_subcommand_via_main(tmp_path: Path) -> None:
    """Validates invocation of 'dashboard show' subcommand via main app."""
    db_file: Path = tmp_path / "test_finances.db"
    conn: sqlite3.Connection = sqlite3.connect(db_file)
    try:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY, date TEXT, "
            "total_value_eur REAL);"
        )
        cursor.execute(
            "CREATE TABLE assets (id INTEGER PRIMARY KEY, ticker TEXT, "
            "name TEXT, type TEXT);"
        )
        cursor.execute(
            "CREATE TABLE asset_snapshots (id INTEGER PRIMARY KEY, "
            "snapshot_id INTEGER, asset_id INTEGER, quantity REAL, "
            "value_eur REAL);"
        )
        cursor.execute("INSERT INTO snapshots VALUES (1, '2026-08-01', 1000.0);")
        cursor.execute("INSERT INTO assets VALUES (1, 'AAPL', 'Apple Inc.', 'STOCK');")
        cursor.execute("INSERT INTO asset_snapshots VALUES (1, 1, 1, 5.0, 1000.0);")
        conn.commit()
    finally:
        conn.close()

    result: Any = runner.invoke(app, ["dashboard", "show", "--db-path", str(db_file)])
    assert result.exit_code == 0
    assert "GLOBAL PORTFOLIO EXECUTIVE SUMMARY" in result.output


# --- SAVE SNAPSHOT COMMAND TESTS ---


def test_save_snapshot_command_success() -> None:
    """Tests 'save-snapshot' CLI command on successful execution and push."""
    mock_snapshot: PortfolioSnapshot = PortfolioSnapshot(
        timestamp="2026-08-16T20:00:00",
        total_value_eur=1000.0,
        assets_snapshot=[],
    )
    with (
        patch("main.get_snapshot", return_value=mock_snapshot),
        patch("main.save_snapshot") as mock_save,
    ):
        result: Any = runner.invoke(app, ["save-snapshot"])
        assert result.exit_code == 0
        mock_save.assert_called_once_with(mock_snapshot)


def test_save_snapshot_command_failure() -> None:
    """Tests 'save-snapshot' CLI command exiting with code 1 on failure."""
    with patch("main.get_snapshot", return_value=None):
        result: Any = runner.invoke(app, ["save-snapshot"])
        assert result.exit_code == 1


def test_save_snapshot_command_unexpected_exception() -> None:
    """Tests 'save-snapshot' CLI command handling unexpected exception."""
    with patch("main.get_snapshot", side_effect=RuntimeError("Unexpected error")):
        result: Any = runner.invoke(app, ["save-snapshot"])
        assert result.exit_code == 1


# --- ANALYZE QUALITY COMMAND TESTS ---


@patch("main.analyze_quality_cmd")
def test_analyze_quality_command_success(mock_analyze: MagicMock) -> None:
    """Tests 'analyze-quality' CLI command execution on success."""
    result: Any = runner.invoke(app, ["analyze-quality"])
    assert result.exit_code == 0
    mock_analyze.assert_called_once_with(ticker=None, notify=False)


@patch("main.analyze_quality_cmd")
def test_analyze_quality_command_exception(mock_analyze: MagicMock) -> None:
    """Tests 'analyze-quality' CLI command exiting code 1 on exception."""
    mock_analyze.side_effect = RuntimeError("Analysis error")
    result: Any = runner.invoke(app, ["analyze-quality"])
    assert result.exit_code == 1


# --- PULL CONFIG COMMAND TESTS ---


@patch("main._pull_cloud_data", return_value=True)
def test_pull_config_command_success(mock_pull: MagicMock) -> None:
    """Tests 'pull-config' CLI command on successful batch sync download."""
    result: Any = runner.invoke(app, ["pull-config"])

    assert result.exit_code == 0
    assert "Successfully pulled configuration files" in result.output


@patch("main._pull_cloud_data", return_value=False)
def test_pull_config_command_failure(mock_pull: MagicMock) -> None:
    """Tests 'pull-config' CLI command when batch sync download fails."""
    result: Any = runner.invoke(app, ["pull-config"])

    assert result.exit_code == 0
    assert "One or more configuration files failed to download" in result.output


@patch("main._pull_cloud_data", side_effect=RuntimeError("Drive error"))
def test_pull_config_command_exception(mock_pull: MagicMock) -> None:
    """Tests 'pull-config' CLI command handling exception during execution."""
    result: Any = runner.invoke(app, ["pull-config"])

    assert result.exit_code == 1


# --- PUSH CONFIG COMMAND TESTS ---


@patch("main._push_cloud_data", return_value=True)
def test_push_config_command_success(mock_push: MagicMock) -> None:
    """Tests 'push-config' CLI command on successful batch sync upload."""
    result: Any = runner.invoke(app, ["push-config"])

    assert result.exit_code == 0
    assert "Successfully pushed configuration files" in result.output


@patch("main._push_cloud_data", return_value=False)
def test_push_config_command_upload_failed(mock_push: MagicMock) -> None:
    """Tests 'push-config' CLI command when batch upload fails."""
    result: Any = runner.invoke(app, ["push-config"])

    assert result.exit_code == 0
    assert "One or more configuration files failed to upload" in result.output


@patch("main._push_cloud_data", side_effect=RuntimeError("Drive error"))
def test_push_config_command_exception(mock_push: MagicMock) -> None:
    """Tests 'push-config' CLI command handling exception during execution."""
    result: Any = runner.invoke(app, ["push-config"])

    assert result.exit_code == 1


# --- ETF DETAILS HELPERS & COMMAND TESTS ---


def test_display_single_etf_details_provider_exception() -> None:
    """Tests _display_single_etf_details when provider raises an exception."""
    mock_provider: MagicMock = MagicMock()
    mock_provider.get_details.side_effect = RuntimeError("Scraper failed")
    asset: Asset = Asset(
        isin="IE00B4L5Y983",
        name="Test ETF",
        yahoo_ticker="EUNL.DE",
        quantity=0.0,
        average_buy_price=0.0,
        asset_type="ETF",
    )
    with pytest.raises(RuntimeError, match="Scraper failed"):
        _display_single_etf_details(asset, mock_provider)
    mock_provider.get_details.assert_called_once()


def test_display_single_etf_details_provider_returns_none() -> None:
    """Tests _display_single_etf_details when provider returns None."""
    mock_provider: MagicMock = MagicMock()
    mock_provider.get_details.return_value = None
    asset: Asset = Asset(
        isin="IE00B4L5Y983",
        name="Test ETF",
        yahoo_ticker="EUNL.DE",
        quantity=0.0,
        average_buy_price=0.0,
        asset_type="ETF",
    )
    _display_single_etf_details(asset, mock_provider)
    mock_provider.get_details.assert_called_once()


@patch("main.ETFProvider")
@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_single_isin_success(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'etf-details' CLI command for a specific ISIN matched in repo."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Core MSCI World USD (Acc)",
            isin="IE00B4L5Y983",
            yahoo_ticker="EUNL.DE",
            quantity=1.0,
            average_buy_price=90.0,
            asset_type="etf",
        )
    ]

    mock_provider.get_details.return_value = ETFDetails(
        holdings=[
            Holding(
                name="Apple",
                isin="US0378331005",
                ticker="AAPL",
                weight_pct=5.0,
            )
        ],
        sector_breakdown=[SectorExposure(sector_name="Tech", weight_pct=30.0)],
        country_breakdown=[CountryExposure(country_name="USA", weight_pct=70.0)],
        ter_pct=0.20,
    )
    mock_provider.get_market_data.return_value = ETFMarketData(
        price=95.0, currency="EUR"
    )

    result: Any = runner.invoke(app, ["etf-details", "IE00B4L5Y983"])

    assert result.exit_code == 0
    assert "ETF DETAILS - EUNL.DE" in result.output
    assert "TER:" in result.output
    assert "0.20%" in result.output
    assert "Apple" in result.output
    assert "5.00%" in result.output
    assert "95.00 EUR" in result.output


def test_etf_details_cmd_invalid_isin() -> None:
    """Tests 'etf-details' CLI command with an invalid ISIN length."""
    result: Any = runner.invoke(app, ["etf-details", "INVALID"])

    assert result.exit_code == 1


@patch("main.ETFProvider")
@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_single_isin_repo_exception(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'etf-details' CLI command when repo throws exception."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.side_effect = Exception("DB Read Error")

    mock_provider.get_details.return_value = ETFDetails(
        holdings=[],
        sector_breakdown=[],
        country_breakdown=[],
        ter_pct=0.15,
    )
    mock_provider.get_market_data.return_value = None

    result: Any = runner.invoke(app, ["etf-details", "IE00B4L5Y983"])

    assert result.exit_code == 0
    assert "IE00B4L5Y983" in result.output


@patch("main.ETFProvider")
@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_empty_breakdowns_and_holding_without_isin(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests formatting branches for empty breakdowns and holding missing ISIN."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_provider.get_details.return_value = ETFDetails(
        holdings=[
            Holding(
                name="Unlisted Asset",
                isin=None,
                ticker=None,
                weight_pct=10.0,
            )
        ],
        sector_breakdown=[],
        country_breakdown=[],
        ter_pct=None,
    )
    mock_provider.get_market_data.return_value = None

    result: Any = runner.invoke(app, ["etf-details", "IE00B4L5Y983"])

    assert result.exit_code == 0
    assert "TER:" in result.output
    assert "N/A" in result.output
    assert "Unlisted Asset" in result.output
    assert "10.00%" in result.output


@patch("main.ETFProvider")
@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_all_etfs_success(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'etf-details' CLI command inspecting all ETFs in portfolio."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Core MSCI World USD (Acc)",
            isin="IE00B4L5Y983",
            yahoo_ticker="EUNL.DE",
            quantity=10.0,
            average_buy_price=80.0,
            asset_type="etf",
        )
    ]

    mock_provider.get_details.return_value = ETFDetails(
        holdings=[],
        sector_breakdown=[],
        country_breakdown=[],
        ter_pct=0.20,
    )
    mock_provider.get_market_data.return_value = ETFMarketData(
        price=88.50, currency="EUR"
    )

    result: Any = runner.invoke(app, ["etf-details"])

    assert result.exit_code == 0
    assert "Core MSCI World USD (Acc)" in result.output


@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_all_etfs_no_etfs_found(
    mock_repo_cls: MagicMock,
) -> None:
    """Tests 'etf-details' CLI command when no active ETF holdings exist."""
    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Apple Inc.",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            quantity=5.0,
            average_buy_price=150.0,
            asset_type="stock",
        )
    ]

    result: Any = runner.invoke(app, ["etf-details"])

    assert result.exit_code == 0
    assert "No active ETF holdings found in portfolio." in result.output


@patch("main.SqlitePortfolioRepository")
def test_etf_details_cmd_all_etfs_repo_exception(
    mock_repo_cls: MagicMock,
) -> None:
    """Tests 'etf-details' CLI command exiting code 1 when repo fails."""
    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.side_effect = Exception("Database unreadable")

    result: Any = runner.invoke(app, ["etf-details"])

    assert result.exit_code == 1


# --- MARKET CAP HELPER UNIT TESTS ---


def test_format_market_cap_helper() -> None:
    """Validates numeric formatting helper for market cap scales."""
    assert _format_market_cap(None) == "N/A"
    assert _format_market_cap(3.5e12) == "3.50T"
    assert _format_market_cap(2.1e9) == "2.10B"
    assert _format_market_cap(15.4e6) == "15.40M"
    assert _format_market_cap(500000.0) == "500000.00"


# --- STOCK DETAILS HELPERS & COMMAND TESTS ---


def test_display_single_stock_details_provider_exception() -> None:
    """Tests _display_single_stock_details when provider raises exception."""
    mock_provider: MagicMock = MagicMock()
    mock_provider.get_details.side_effect = RuntimeError("yfinance failure")

    with pytest.raises(RuntimeError, match="yfinance failure"):
        _display_single_stock_details("AAPL", "Apple", mock_provider)
    mock_provider.get_details.assert_called_once()


def test_display_single_stock_details_provider_returns_none() -> None:
    """Tests _display_single_stock_details when provider returns None."""
    mock_provider: MagicMock = MagicMock()
    mock_provider.get_details.return_value = None

    _display_single_stock_details("AAPL", "Apple", mock_provider)
    mock_provider.get_details.assert_called_once()


@patch("main.StockProvider")
@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_single_stock_success_with_all_metrics(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'stock-details' with all fundamental metrics populated."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Apple",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            quantity=1.0,
            average_buy_price=180.0,
            asset_type="stock",
        )
    ]

    mock_provider.get_price.return_value = Quotation(price=180.0, currency="USD")
    mock_provider.get_details.return_value = StockDetails(
        sector="Technology",
        industry="Consumer Electronics",
        market_cap=3000000000000.0,
        pe_ratio=30.0,
        forward_pe=25.0,
        dividend_yield_pct=0.5,
        currency="USD",
    )

    result: Any = runner.invoke(app, ["stock-details", "AAPL"])

    assert result.exit_code == 0
    assert "STOCK DETAILS - AAPL" in result.output
    assert "Sector:" in result.output
    assert "Technology" in result.output
    assert "P/E (Trailing):" in result.output


@patch("main.StockProvider")
@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_matched_by_isin(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'stock-details' CLI command matching stock by ISIN."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Microsoft",
            isin="US5949181045",
            yahoo_ticker="MSFT",
            quantity=2.0,
            average_buy_price=300.0,
            asset_type="stock",
        )
    ]

    mock_provider.get_price.return_value = Quotation(price=300.0, currency="USD")
    mock_provider.get_details.return_value = StockDetails(
        sector="Software",
        industry="Infrastructure Software",
        market_cap=2500000000000.0,
        pe_ratio=32.0,
        forward_pe=28.0,
        dividend_yield_pct=0.8,
        currency="USD",
    )

    result: Any = runner.invoke(app, ["stock-details", "US5949181045"])

    assert result.exit_code == 0
    assert "Microsoft" in result.output


@patch("main.StockProvider")
@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_single_stock_repo_exception(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'stock-details' CLI command when repo load raises exception."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.side_effect = Exception("DB Error")

    mock_provider.get_price.return_value = Quotation(price=100.0, currency="USD")
    mock_provider.get_details.return_value = StockDetails(
        sector="Tech",
        industry="Hardware",
        market_cap=100.0,
        pe_ratio=10.0,
        forward_pe=8.0,
        dividend_yield_pct=1.0,
        currency="USD",
    )

    result: Any = runner.invoke(app, ["stock-details", "AAPL"])

    assert result.exit_code == 0
    assert "AAPL" in result.output


@patch("main.StockProvider")
@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_formatting_none_fields(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests metrics formatting when StockDetails fields are None."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_provider.get_price.return_value = None
    mock_provider.get_details.return_value = StockDetails(
        sector=None,
        industry=None,
        market_cap=None,
        pe_ratio=None,
        forward_pe=None,
        dividend_yield_pct=None,
    )

    result: Any = runner.invoke(app, ["stock-details", "AAPL"])

    assert result.exit_code == 0
    assert "Sector:" in result.output
    assert "N/A" in result.output


@patch("main.StockProvider")
@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_all_stocks_success(
    mock_repo_cls: MagicMock, mock_provider_cls: MagicMock
) -> None:
    """Tests 'stock-details' CLI command inspecting all stocks in portfolio."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = [
        Asset(
            name="Tesla Inc.",
            isin="US88160R1014",
            yahoo_ticker="TSLA",
            quantity=10.0,
            average_buy_price=200.0,
            asset_type="stock",
        )
    ]

    mock_provider.get_price.return_value = Quotation(price=200.0, currency="USD")
    mock_provider.get_details.return_value = StockDetails(
        sector="Automotive",
        industry="EV",
        market_cap=800e9,
        pe_ratio=40.0,
        forward_pe=35.0,
        dividend_yield_pct=0.0,
        currency="USD",
    )

    result: Any = runner.invoke(app, ["stock-details"])

    assert result.exit_code == 0
    assert "TSLA" in result.output


@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_all_stocks_no_stocks_found(
    mock_repo_cls: MagicMock,
) -> None:
    """Tests 'stock-details' CLI command when no active stock holdings exist."""
    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.return_value = []

    result: Any = runner.invoke(app, ["stock-details"])

    assert result.exit_code == 0
    assert "No active stock holdings found in portfolio." in result.output


@patch("main.SqlitePortfolioRepository")
def test_stock_details_cmd_all_stocks_repo_exception(
    mock_repo_cls: MagicMock,
) -> None:
    """Tests 'stock-details' CLI command exiting code 1 when repo fails."""
    mock_repo: MagicMock = MagicMock()
    mock_repo_cls.return_value = mock_repo
    mock_repo.load_assets.side_effect = Exception("DB Connection Error")

    result: Any = runner.invoke(app, ["stock-details"])

    assert result.exit_code == 1


# --- EXPOSURE CHECK COMMAND TESTS ---


@patch("main.SqliteHistoryRepository")
@patch("main.ExposureEngine")
def test_exposure_check_cmd_success_no_violations(
    mock_exposure_cls: MagicMock, mock_history_cls: MagicMock
) -> None:
    """Tests 'exposure-check' CLI command execution with no violations."""
    mock_history: MagicMock = MagicMock()
    mock_history_cls.return_value = mock_history
    mock_snapshot = PortfolioSnapshot(
        timestamp="2026-08-21", total_value_eur=1000.0, assets_snapshot=[]
    )
    mock_history.load_history.return_value = [mock_snapshot]

    mock_engine: MagicMock = MagicMock()
    mock_exposure_cls.return_value = mock_engine
    mock_engine.calculate_consolidated_exposure.return_value = (
        {"Technology": 30.0},
        {"United States": 40.0},
    )
    mock_engine.calculate_company_exposure.return_value = {"Apple Inc.": 10.0}
    mock_engine.validate_exposure_limits.return_value = []
    mock_engine.validate_company_limits.return_value = []

    result: Any = runner.invoke(app, ["exposure-check"])

    assert result.exit_code == 0
    assert "Consolidated Sector Exposure:" in result.output
    assert "Consolidated Country Exposure:" in result.output
    assert "All exposure limits are respected" in result.output


@patch("main.SqliteHistoryRepository")
@patch("main.ExposureEngine")
def test_exposure_check_cmd_with_violations(
    mock_exposure_cls: MagicMock, mock_history_cls: MagicMock
) -> None:
    """Tests 'exposure-check' CLI command when violations detected."""
    mock_history: MagicMock = MagicMock()
    mock_history_cls.return_value = mock_history
    mock_snapshot = PortfolioSnapshot(
        timestamp="2026-08-21", total_value_eur=1000.0, assets_snapshot=[]
    )
    mock_history.load_history.return_value = [mock_snapshot]

    mock_engine: MagicMock = MagicMock()
    mock_exposure_cls.return_value = mock_engine
    mock_engine.calculate_consolidated_exposure.return_value = (
        {"Technology": 60.0},
        {"United States": 70.0},
    )
    mock_engine.calculate_company_exposure.return_value = {"Apple Inc.": 20.0}
    mock_engine.validate_exposure_limits.return_value = ["Sector limit exceeded"]
    mock_engine.validate_company_limits.return_value = ["Company limit exceeded"]

    result: Any = runner.invoke(app, ["exposure-check"])

    assert result.exit_code == 0
    assert "Policy Violations Detected" in result.output
    assert "Sector limit exceeded" in result.output


@patch("main.SqliteHistoryRepository")
def test_exposure_check_cmd_no_history(
    mock_history_cls: MagicMock,
) -> None:
    """Tests 'exposure-check' CLI command when history storage is empty."""
    mock_history: MagicMock = MagicMock()
    mock_history_cls.return_value = mock_history
    mock_history.load_history.return_value = []

    result: Any = runner.invoke(app, ["exposure-check"])

    assert result.exit_code == 0
    assert "No portfolio history found for exposure check." in result.output


# --- OPPORTUNITY COMMAND TESTS ---


@patch("main.recommend_rebalance")
def test_opportunity_command_defaults(
    mock_recommend: MagicMock,
) -> None:
    """Tests 'opportunity_evaluation' CLI command with default options."""
    result: Any = runner.invoke(app, ["opportunity_evaluation"])

    assert result.exit_code == 0
    mock_recommend.assert_called_once()
    _, kwargs = mock_recommend.call_args
    assert kwargs["skip_ai"] is False
    assert kwargs["verbose"] is False


@patch("main.recommend_rebalance")
def test_opportunity_command_custom_options(
    mock_recommend: MagicMock,
) -> None:
    """Tests 'opportunity_evaluation' CLI command with custom options."""
    result: Any = runner.invoke(
        app,
        [
            "opportunity_evaluation",
            "--targets-file",
            "custom_targets.json",
            "--portfolio-file",
            "custom_portfolio.json",
            "--skip-ai",
            "-v",
        ],
    )

    assert result.exit_code == 0
    mock_recommend.assert_called_once()
    _, kwargs = mock_recommend.call_args
    assert str(kwargs["targets_file"]) == "custom_targets.json"
    assert str(kwargs["portfolio_file"]) == "custom_portfolio.json"
    assert kwargs["skip_ai"] is True
    assert kwargs["verbose"] is True


# --- SYNC FUNDAMENTALS COMMAND TESTS ---


@patch("main.sync_portfolio_fundamentals")
def test_sync_fundamentals_command_success(
    mock_sync: MagicMock,
) -> None:
    """Tests 'sync-fundamentals' CLI command on successful execution."""
    result: Any = runner.invoke(app, ["sync-fundamentals"])

    assert result.exit_code == 0
    mock_sync.assert_called_once()


@patch("main.sync_portfolio_fundamentals")
def test_sync_fundamentals_command_exception(
    mock_sync: MagicMock,
) -> None:
    """Tests 'sync-fundamentals' CLI command handling exception."""
    mock_sync.side_effect = RuntimeError("Database error")

    result: Any = runner.invoke(app, ["sync-fundamentals"])

    assert result.exit_code == 1


# --- MAIN MODULE ENTRYPOINT TEST ---


def test_main_module_execution() -> None:
    """Tests __main__ execution block for main.py."""
    with (
        patch("sys.argv", ["main.py", "--help"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        import runpy

        runpy.run_module("main", run_name="__main__")

    assert exc_info.value.code == 0
