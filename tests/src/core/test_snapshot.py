"""Unit tests for portfolio snapshot logic in src/core/snapshot.py covering calculation,
concurrency, display, storage error handling, and Google Drive backups.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import StorageError
from src.core.models import Asset, AssetSnapshot, PortfolioSnapshot, Quotation
from src.core.providers import ETFProvider, StockProvider
from src.core.snapshot import (
    display_snapshot,
    get_provider_for_asset,
    get_snapshot,
    save_snapshot,
    trigger_gdrive_backup,
)


@pytest.fixture(autouse=True)
def mock_provider_details() -> Generator[None]:
    """Mocks provider details to prevent unmocked yfinance SQLite init."""
    with (
        patch("src.core.providers.StockProvider.get_details", return_value=None),
        patch("src.core.providers.ETFProvider.get_details", return_value=None),
    ):
        yield


@pytest.fixture
def sample_assets() -> list[Asset]:
    return [
        Asset(
            name="Apple Inc.",
            isin="US0378331005",
            yahoo_ticker="AAPL",
            quantity=10,
            average_buy_price=150.0,
            asset_type="stock",
        ),
        Asset(
            name="iShares MSCI World",
            isin="IE00B4L5Y983",
            yahoo_ticker="EUNL.DE",
            quantity=5,
            average_buy_price=80.0,
            asset_type="etf",
        ),
    ]


@pytest.fixture
def sample_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp="2026-08-19T09:00:00",
        total_value_eur=2045.00,
        assets_snapshot=[
            AssetSnapshot(
                name="Apple Inc.",
                isin="US0378331005",
                yahoo_ticker="AAPL",
                native_price=180.0,
                native_currency="USD",
                value_eur=1620.00,
            ),
            AssetSnapshot(
                name="iShares MSCI World",
                isin="IE00B4L5Y983",
                yahoo_ticker="EUNL.DE",
                native_price=85.0,
                native_currency="EUR",
                value_eur=425.00,
            ),
        ],
    )


# ==============================================================================
# Provider Factory Tests
# ==============================================================================


def test_get_provider_for_asset_etf() -> None:
    """Validates that get_provider_for_asset returns ETFProvider for etf asset_type."""
    asset = Asset(
        name="MSCI World",
        isin="IE00B4L5Y983",
        yahoo_ticker="EUNL.DE",
        quantity=5,
        average_buy_price=80.0,
        asset_type="etf",
    )
    provider = get_provider_for_asset(asset)
    assert isinstance(provider, ETFProvider)


def test_get_provider_for_asset_stock_default() -> None:
    """Validates get_provider_for_asset returns StockProvider for stock type."""
    asset = Asset(
        name="Apple Inc.",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10,
        average_buy_price=150.0,
        asset_type="stock",
    )
    provider = get_provider_for_asset(asset)
    assert isinstance(provider, StockProvider)


# ==============================================================================
# get_snapshot Tests
# ==============================================================================


@patch("src.core.snapshot.get_exchange_rate")
@patch("src.core.providers.StockProvider.get_price")
@patch("src.core.providers.ETFProvider.get_price")
def test_get_snapshot_multi_currency(
    mock_etf_price: MagicMock,
    mock_stock_price: MagicMock,
    mock_get_fx: MagicMock,
    sample_assets: list[Asset],
) -> None:
    """Validates calculation of total portfolio value across multiple currencies."""
    mock_stock_price.return_value = Quotation(price=180.0, currency="USD")
    mock_etf_price.return_value = Quotation(price=85.0, currency="EUR")
    mock_get_fx.return_value = 0.90  # 1 USD = 0.90 EUR

    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.return_value = sample_assets

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is not None
    assert len(snapshot.assets_snapshot) == 2
    # AAPL: 10 * 180 USD * 0.90 = 1620.00 EUR
    # EUNL: 5 * 85 EUR * 1.0 = 425.00 EUR
    assert snapshot.total_value_eur == 2045.00


@patch("src.core.snapshot.get_exchange_rate")
@patch("src.core.providers.StockProvider.get_price")
def test_get_snapshot_currency_caching(
    mock_get_price: MagicMock,
    mock_get_fx: MagicMock,
    sample_assets: list[Asset],
) -> None:
    """Validates that FX rate calls are cached per currency during calculation."""
    mock_get_price.return_value = Quotation(price=100.0, currency="USD")
    mock_get_fx.return_value = 0.85

    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.return_value = sample_assets

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is not None
    mock_get_fx.assert_called_once_with("USD", "EUR")


@patch("src.core.snapshot.get_exchange_rate")
@patch("src.core.providers.StockProvider.get_price")
def test_get_snapshot_missing_asset_quotation(
    mock_get_price: MagicMock,
    mock_get_fx: MagicMock,
    sample_assets: list[Asset],
) -> None:
    """Validates assets with missing quotations are skipped from snapshot."""
    mock_get_price.side_effect = [None, Quotation(price=80.0, currency="EUR")]

    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.return_value = sample_assets

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is not None
    assert len(snapshot.assets_snapshot) == 1
    assert snapshot.assets_snapshot[0].yahoo_ticker == "EUNL.DE"


@patch("src.core.snapshot.get_exchange_rate")
@patch("src.core.providers.StockProvider.get_price")
def test_get_snapshot_exchange_rate_failure(
    mock_get_price: MagicMock,
    mock_get_fx: MagicMock,
    sample_assets: list[Asset],
) -> None:
    """Validates assets are skipped when exchange rate lookup fails."""
    mock_get_price.return_value = Quotation(price=100.0, currency="USD")
    mock_get_fx.return_value = None

    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.return_value = sample_assets

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is not None
    assert len(snapshot.assets_snapshot) == 0
    assert snapshot.total_value_eur == 0.0


def test_get_snapshot_empty_portfolio() -> None:
    """Validates get_snapshot returns zero total value when portfolio is empty."""
    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.return_value = []

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is not None
    assert snapshot.total_value_eur == 0.0
    assert snapshot.assets_snapshot == []


@patch("src.core.snapshot.logger")
def test_get_snapshot_storage_error(mock_logger: MagicMock) -> None:
    """Validates get_snapshot logs error and returns None on StorageError."""
    mock_repo: MagicMock = MagicMock()
    mock_repo.load_assets.side_effect = StorageError("Read failed")

    snapshot: PortfolioSnapshot | None = get_snapshot(portfolio_repo=mock_repo)

    assert snapshot is None
    mock_logger.error.assert_called_once()


@patch("src.core.snapshot.SqlitePortfolioRepository")
def test_get_snapshot_default_repository(mock_repo_cls: MagicMock) -> None:
    """Validates get_snapshot creates default repository when None provided."""
    mock_repo_inst: MagicMock = MagicMock()
    mock_repo_inst.load_assets.return_value = []
    mock_repo_cls.return_value = mock_repo_inst

    get_snapshot(portfolio_repo=None)

    mock_repo_cls.assert_called_once()


# ==============================================================================
# display_snapshot Tests
# ==============================================================================


@patch("src.core.snapshot.logger")
def test_display_snapshot_with_object(
    mock_logger: MagicMock, sample_snapshot: PortfolioSnapshot
) -> None:
    """Validates display_snapshot logs metrics for PortfolioSnapshot instance."""
    display_snapshot(sample_snapshot)

    mock_logger.section.assert_called_once_with("Displaying Snapshot")
    mock_logger.info.assert_any_call(f"Timestamp: {sample_snapshot.timestamp}")
    mock_logger.info.assert_any_call("Total Portfolio Value: 2045.00 EUR")


@patch("src.core.snapshot.logger")
def test_display_snapshot_with_dict(
    mock_logger: MagicMock, sample_snapshot: PortfolioSnapshot
) -> None:
    """Validates display_snapshot converts dictionary input to PortfolioSnapshot."""
    snapshot_dict = sample_snapshot.to_dict()
    display_snapshot(snapshot_dict)

    mock_logger.info.assert_any_call("Total Portfolio Value: 2045.00 EUR")


# ==============================================================================
# trigger_gdrive_backup Tests
# ==============================================================================


@patch("src.core.snapshot.GDriveService")
def test_trigger_gdrive_backup_success(
    mock_gdrive_cls: MagicMock, tmp_path: Path
) -> None:
    """Validates trigger_gdrive_backup when backup operation succeeds."""
    mock_service = MagicMock()
    mock_service.backup_file.return_value = True
    mock_gdrive_cls.return_value = mock_service

    test_file = tmp_path / "test.db"
    test_file.touch()

    result = trigger_gdrive_backup(test_file, folder_id="folder123")

    assert result is True
    mock_gdrive_cls.assert_called_once_with(folder_id="folder123")
    mock_service.backup_file.assert_called_once_with(test_file)


@patch("src.core.snapshot.GDriveService")
def test_trigger_gdrive_backup_failure(
    mock_gdrive_cls: MagicMock, tmp_path: Path
) -> None:
    """Validates trigger_gdrive_backup returns False when backup operation fails."""
    mock_service = MagicMock()
    mock_service.backup_file.return_value = False
    mock_gdrive_cls.return_value = mock_service

    test_file = tmp_path / "test.db"

    result = trigger_gdrive_backup(test_file)

    assert result is False


@patch("src.core.snapshot.GDriveService")
def test_trigger_gdrive_backup_exception_handling(
    mock_gdrive_cls: MagicMock, tmp_path: Path
) -> None:
    """Validates trigger_gdrive_backup handles exceptions gracefully without raising."""
    mock_gdrive_cls.side_effect = Exception("Auth failed")

    test_file = tmp_path / "test.db"

    result = trigger_gdrive_backup(test_file)

    assert result is False


# ==============================================================================
# save_snapshot Tests
# ==============================================================================


@patch("src.core.snapshot.trigger_gdrive_backup")
def test_save_snapshot_success(
    mock_backup: MagicMock, sample_snapshot: PortfolioSnapshot, tmp_path: Path
) -> None:
    """Validates save_snapshot persists data and triggers Google Drive backup."""
    mock_repo = MagicMock()
    db_file = tmp_path / "finances.db"
    db_file.touch()

    with patch("src.core.snapshot.DEFAULT_DB_PATH", str(db_file)):
        save_snapshot(sample_snapshot, history_repo=mock_repo, backup_to_gdrive=True)

    mock_repo.save_snapshot.assert_called_once_with(sample_snapshot)
    mock_backup.assert_called_with(db_file)


@patch("src.core.snapshot.logger")
def test_save_snapshot_storage_error(
    mock_logger: MagicMock, sample_snapshot: PortfolioSnapshot
) -> None:
    """Validates save_snapshot logs error when HistoryRepository raises StorageError."""
    mock_repo = MagicMock()
    mock_repo.save_snapshot.side_effect = StorageError("Write failed")

    save_snapshot(sample_snapshot, history_repo=mock_repo, backup_to_gdrive=False)

    mock_logger.error.assert_called_once()


@patch("src.core.snapshot.trigger_gdrive_backup")
def test_save_snapshot_without_gdrive_backup(
    mock_backup: MagicMock, sample_snapshot: PortfolioSnapshot
) -> None:
    """Validates save_snapshot skips Google Drive backups when disabled."""
    mock_repo = MagicMock()

    save_snapshot(sample_snapshot, history_repo=mock_repo, backup_to_gdrive=False)

    mock_repo.save_snapshot.assert_called_once_with(sample_snapshot)
    mock_backup.assert_not_called()


@patch("src.core.snapshot.SqliteHistoryRepository")
def test_save_snapshot_default_repository(
    mock_repo_cls: MagicMock, sample_snapshot: PortfolioSnapshot
) -> None:
    """Validates save_snapshot creates SqliteHistoryRepository if None."""
    mock_repo_inst = MagicMock()
    mock_repo_cls.return_value = mock_repo_inst

    save_snapshot(sample_snapshot, history_repo=None, backup_to_gdrive=False)

    mock_repo_cls.assert_called_once()
    mock_repo_inst.save_snapshot.assert_called_once()
