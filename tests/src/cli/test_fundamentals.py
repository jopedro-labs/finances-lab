"""Unit tests for stock and ETF fundamental repository and CLI sync logic.

Covers repository persistence, stock/ETF sync loops, provider None returns,
loop exceptions, database failure exits, empty asset states, portfolio sync,
and CLI argument parsing in main().
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli.fundamentals import (
    main,
    sync_etf_fundamentals,
    sync_portfolio_fundamentals,
    sync_stock_fundamentals,
)
from src.core.models import (
    Asset,
    CountryExposure,
    ETFDetails,
    Holding,
    SectorExposure,
    StockDetails,
)
from src.core.repositories import SqliteOpportunityRepository
from src.infra.database.connection import get_db_context
from src.infra.database.schema import initialize_database


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Fixture providing an initialized temporary SQLite database path."""
    db_file: Path = tmp_path / "test_finances.db"
    with get_db_context(str(db_file)) as conn:
        initialize_database(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assets (
                id, isin, name, yahoo_ticker, quantity,
                average_buy_price, asset_type
            ) VALUES
            (1, 'US0378331005', 'Apple Inc.', 'AAPL', 10.0, 150.0, 'STOCK'),
            (2, 'IE00BK5BQT36', 'Vanguard All-World', 'VWCE.DE', 5.0, 100.0, 'ETF');
            """)
        conn.commit()
    return db_file


@pytest.fixture
def empty_db_path(tmp_path: Path) -> Path:
    """Fixture providing an initialized SQLite database without assets."""
    db_file: Path = tmp_path / "empty_finances.db"
    with get_db_context(str(db_file)) as conn:
        initialize_database(conn)
    return db_file


# ==============================================================================
# Repository Persistence Tests
# ==============================================================================


def test_save_stock_fundamentals_success(temp_db_path: Path) -> None:
    """Tests persisting stock fundamental details into SQLite database."""
    repo: SqliteOpportunityRepository = SqliteOpportunityRepository(
        db_path=temp_db_path
    )
    details: StockDetails = StockDetails(
        market_cap=2_500_000_000_000.0,
        pe_ratio=30.5,
        forward_pe=28.0,
        dividend_yield_pct=0.5,
        fifty_two_week_high=200.0,
        fifty_two_week_low=150.0,
        sector="Technology",
        industry="Consumer Electronics",
    )

    repo.save_stock_fundamentals(asset_id=1, details=details)

    with get_db_context(str(temp_db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT asset_id, market_cap, sector "
            "FROM stock_fundamental_history WHERE asset_id = 1"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["asset_id"] == 1
        assert row["market_cap"] == 2_500_000_000_000.0
        assert row["sector"] == "Technology"


def test_save_etf_fundamentals_success(temp_db_path: Path) -> None:
    """Tests persisting ETF fundamental details into SQLite database."""
    repo: SqliteOpportunityRepository = SqliteOpportunityRepository(
        db_path=temp_db_path
    )
    details: ETFDetails = ETFDetails(
        ter_pct=0.22,
        holdings=[
            Holding(
                name="Microsoft Corp",
                isin="US5949181045",
                ticker="MSFT",
                weight_pct=4.5,
            )
        ],
        sector_breakdown=[
            SectorExposure(
                sector_name="Technology",
                weight_pct=25.0,
            )
        ],
        country_breakdown=[
            CountryExposure(
                country_name="United States",
                weight_pct=60.0,
            )
        ],
    )

    repo.save_etf_fundamentals(asset_id=2, details=details)

    with get_db_context(str(temp_db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT asset_id, ter_pct, holdings_json "
            "FROM etf_fundamental_history WHERE asset_id = 2"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["asset_id"] == 2
        assert row["ter_pct"] == 0.22
        holdings = json.loads(row["holdings_json"])
        assert len(holdings) == 1
        assert holdings[0]["name"] == "Microsoft Corp"


# ==============================================================================
# Stock Sync Logic Tests
# ==============================================================================


@patch("src.cli.fundamentals.StockProvider")
def test_sync_stock_fundamentals_cli_success(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Tests the sync_stock_fundamentals CLI execution workflow."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.return_value = StockDetails(
        market_cap=2_500_000_000_000.0,
        pe_ratio=30.5,
        forward_pe=28.0,
        dividend_yield_pct=0.5,
        fifty_two_week_high=200.0,
        fifty_two_week_low=150.0,
        sector="Technology",
        industry="Consumer Electronics",
    )

    sync_stock_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()
    call_arg: Asset = mock_provider.get_details.call_args[0][0]
    assert call_arg.yahoo_ticker == "AAPL"
    assert mock_provider.get_details.call_args.kwargs.get("force_refresh") is True


@patch("src.cli.fundamentals.StockProvider")
def test_sync_stock_fundamentals_no_assets(
    mock_provider_cls: MagicMock, empty_db_path: Path
) -> None:
    """Validates sync_stock_fundamentals returns cleanly when no stocks exist."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    sync_stock_fundamentals(db_path=empty_db_path)

    mock_provider.get_details.assert_not_called()


@patch("src.cli.fundamentals.StockProvider")
def test_sync_stock_fundamentals_details_returns_none(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_stock_fundamentals handles None return from provider."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.return_value = None

    sync_stock_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()


@patch("src.cli.fundamentals.StockProvider")
def test_sync_stock_fundamentals_provider_exception(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_stock_fundamentals catches provider exceptions safely."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.side_effect = Exception("yfinance API error")

    sync_stock_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()


@patch("src.cli.fundamentals.get_db_context")
def test_sync_stock_fundamentals_db_error_exits(
    mock_db_context: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_stock_fundamentals calls sys.exit(1) on database error."""
    mock_db_context.side_effect = Exception("Database connection failure")

    with pytest.raises(SystemExit) as exc_info:
        sync_stock_fundamentals(db_path=temp_db_path)

    assert exc_info.value.code == 1


# ==============================================================================
# ETF Sync Logic Tests
# ==============================================================================


@patch("src.cli.fundamentals.ETFProvider")
def test_sync_etf_fundamentals_cli_success(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Tests the sync_etf_fundamentals CLI execution workflow."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.return_value = ETFDetails(
        ter_pct=0.22,
        holdings=[],
        sector_breakdown=[],
        country_breakdown=[],
    )

    sync_etf_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()
    call_arg: Asset = mock_provider.get_details.call_args[0][0]
    assert call_arg.isin == "IE00BK5BQT36"
    assert mock_provider.get_details.call_args.kwargs.get("force_refresh") is True


@patch("src.cli.fundamentals.ETFProvider")
def test_sync_etf_fundamentals_no_assets(
    mock_provider_cls: MagicMock, empty_db_path: Path
) -> None:
    """Validates sync_etf_fundamentals returns cleanly when no ETFs exist."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider

    sync_etf_fundamentals(db_path=empty_db_path)

    mock_provider.get_details.assert_not_called()


@patch("src.cli.fundamentals.ETFProvider")
def test_sync_etf_fundamentals_details_returns_none(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_etf_fundamentals handles None return from provider."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.return_value = None

    sync_etf_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()


@patch("src.cli.fundamentals.ETFProvider")
def test_sync_etf_fundamentals_provider_exception(
    mock_provider_cls: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_etf_fundamentals catches provider exceptions safely."""
    mock_provider: MagicMock = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.get_details.side_effect = Exception("Scraper network error")

    sync_etf_fundamentals(db_path=temp_db_path)

    mock_provider.get_details.assert_called_once()


@patch("src.cli.fundamentals.get_db_context")
def test_sync_etf_fundamentals_db_error_exits(
    mock_db_context: MagicMock, temp_db_path: Path
) -> None:
    """Validates sync_etf_fundamentals calls sys.exit(1) on database error."""
    mock_db_context.side_effect = Exception("Database connection failure")

    with pytest.raises(SystemExit) as exc_info:
        sync_etf_fundamentals(db_path=temp_db_path)

    assert exc_info.value.code == 1


# ==============================================================================
# Portfolio Sync & Main CLI Entrypoint Tests
# ==============================================================================


@patch("src.cli.fundamentals.ETFProvider")
@patch("src.cli.fundamentals.StockProvider")
def test_sync_portfolio_fundamentals_cli(
    mock_stock_cls: MagicMock,
    mock_etf_cls: MagicMock,
    temp_db_path: Path,
) -> None:
    """Tests full portfolio fundamentals sync (stocks and ETFs)."""
    mock_stock_provider: MagicMock = MagicMock()
    mock_stock_cls.return_value = mock_stock_provider
    mock_stock_provider.get_details.return_value = StockDetails(
        market_cap=1.0,
        pe_ratio=1.0,
        forward_pe=1.0,
        dividend_yield_pct=0.0,
        fifty_two_week_high=1.0,
        fifty_two_week_low=1.0,
        sector="Tech",
        industry="Tech",
    )

    mock_etf_provider: MagicMock = MagicMock()
    mock_etf_cls.return_value = mock_etf_provider
    mock_etf_provider.get_details.return_value = ETFDetails(
        ter_pct=0.2,
        holdings=[],
        sector_breakdown=[],
        country_breakdown=[],
    )

    sync_portfolio_fundamentals(db_path=temp_db_path)

    mock_stock_provider.get_details.assert_called_once()
    mock_etf_provider.get_details.assert_called_once()


@patch("src.cli.fundamentals.sync_portfolio_fundamentals")
def test_main_cli_sync_command(
    mock_sync_portfolio: MagicMock, temp_db_path: Path
) -> None:
    """Validates CLI main parser invoking sync command."""
    test_args: list[str] = [
        "cli.fundamentals",
        "sync",
        "--db-path",
        str(temp_db_path),
    ]

    with patch.object(sys, "argv", test_args):
        main()

    mock_sync_portfolio.assert_called_once_with(db_path=str(temp_db_path))


def test_main_script_execution_block() -> None:
    """Validates direct script entrypoint execution (__name__ == '__main__')."""
    with patch("src.cli.fundamentals.main") as mock_main:
        import src.cli.fundamentals

        with patch.object(src.cli.fundamentals, "__name__", "__main__"):
            mock_main.assert_not_called()
