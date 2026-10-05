"""
This file contains the logic for creating and managing portfolio value snapshots.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import settings
from src.core.currency_exchange import get_exchange_rate
from src.core.exceptions import StorageError
from src.core.models import Asset, AssetSnapshot, PortfolioSnapshot, Quotation
from src.core.providers import AssetDataProvider, ETFProvider, StockProvider
from src.core.repositories import (
    HistoryRepository,
    PortfolioRepository,
    SqliteHistoryRepository,
    SqlitePortfolioRepository,
)
from src.infra.database.connection import DEFAULT_DB_PATH
from src.utils.logger.logger import logger


def get_provider_for_asset(asset: Asset) -> AssetDataProvider:
    """Selects the appropriate data provider based on asset type."""
    asset_type: str = str(getattr(asset, "asset_type", "STOCK")).upper()
    if asset_type == "ETF":
        return ETFProvider()
    return StockProvider()


def get_snapshot(
    portfolio_repo: PortfolioRepository | None = None,
    max_workers: int = 5,
) -> PortfolioSnapshot | None:
    """Calculates current value of all assets in the portfolio concurrently."""
    logger.section("Getting Portfolio Snapshot")

    repo: PortfolioRepository = portfolio_repo or SqlitePortfolioRepository(
        DEFAULT_DB_PATH
    )

    try:
        assets: list[Asset] = repo.load_assets()
    except StorageError as e:
        logger.error(f"Error reading portfolio repository: {e}", exception=e)
        return None

    if not assets:
        logger.warning(
            "Portfolio is empty — no assets found. Returning empty snapshot."
        )
        return PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            total_value_eur=0.0,
            assets_snapshot=[],
        )

    def fetch_asset_quotation(asset: Asset) -> tuple[Asset, Quotation | None]:
        provider: AssetDataProvider = get_provider_for_asset(asset)
        raw_quotation: Quotation | None = provider.get_price(asset)

        provider.get_details(
            asset
        )  # populates provider's internal details cache as a side-effect

        if not raw_quotation:
            return asset, None
        return asset, raw_quotation

    quotations_map: dict[str, Quotation] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: list[Future[tuple[Asset, Quotation | None]]] = [
            executor.submit(fetch_asset_quotation, asset) for asset in assets
        ]
        for future in as_completed(futures):
            asset: Asset
            fetched_quotation: Quotation | None
            asset, fetched_quotation = future.result()
            if fetched_quotation:
                quotations_map[asset.yahoo_ticker] = fetched_quotation
            else:
                logger.warning(f"Skipping {asset.yahoo_ticker} from calculation.")

    assets_snapshot: list[AssetSnapshot] = []
    total_portfolio_value_eur: float = 0.0
    exchange_rates_cache: dict[str, float | None] = {"EUR": 1.0}

    for asset in assets:
        quotation: Quotation | None = quotations_map.get(asset.yahoo_ticker)
        if not quotation:
            continue

        native_price: float = quotation.price
        native_currency: str = quotation.currency.upper()
        value_native: float = native_price * asset.quantity

        if native_currency not in exchange_rates_cache:
            exchange_rates_cache[native_currency] = get_exchange_rate(
                native_currency, "EUR"
            )

        rate: float | None = exchange_rates_cache[native_currency]
        if rate is None:
            logger.warning(
                f"Could not retrieve exchange rate for {native_currency}. "
                f"Skipping {asset.yahoo_ticker} from calculation."
            )
            continue

        value_eur: float = value_native * rate

        assets_snapshot.append(
            AssetSnapshot(
                name=asset.name,
                isin=asset.isin,
                yahoo_ticker=asset.yahoo_ticker,
                native_price=native_price,
                native_currency=native_currency,
                value_eur=round(value_eur, 2),
            )
        )
        total_portfolio_value_eur += value_eur

    return PortfolioSnapshot(
        timestamp=datetime.now().isoformat(),
        total_value_eur=round(total_portfolio_value_eur, 2),
        assets_snapshot=assets_snapshot,
    )


def display_snapshot(snapshot_data: PortfolioSnapshot | dict[str, Any]) -> None:
    """Prints a formatted summary of a snapshot to the console."""
    logger.section("Displaying Snapshot")

    snapshot: PortfolioSnapshot = (
        snapshot_data
        if isinstance(snapshot_data, PortfolioSnapshot)
        else PortfolioSnapshot.from_dict(snapshot_data)
    )

    logger.info(f"Timestamp: {snapshot.timestamp}")
    logger.info(f"Total Portfolio Value: {snapshot.total_value_eur:.2f} EUR")

    for asset in snapshot.assets_snapshot:
        logger.info(f"  - {asset.name}: {asset.value_eur:.2f} EUR")


def trigger_gdrive_backup(file_path: Path, folder_id: str | None = None) -> bool:
    """Triggers non-blocking backup of a persistence file to Google Drive."""
    try:
        from src.infra.gdrive.service import GoogleDriveService

        target_folder: str | None = folder_id or settings.gdrive_snapshot_folder_id
        service: GoogleDriveService = GoogleDriveService(folder_id=target_folder)
        success: bool = service.backup_file(file_path)
        if success:
            logger.success(f"Google Drive backup successful for '{file_path.name}'.")
        else:
            logger.warning(f"Google Drive backup skipped for '{file_path.name}'.")
        return success
    except Exception as e:
        logger.warning(f"Google Drive backup failed gracefully: {e}")
        return False


def save_snapshot(
    snapshot_data: PortfolioSnapshot | dict[str, Any],
    history_repo: HistoryRepository | None = None,
    backup_to_gdrive: bool = True,
) -> None:
    """Appends a snapshot to storage and optionally backs
    up local database to Google Drive."""
    logger.section("Saving Snapshot")

    snapshot: PortfolioSnapshot = (
        snapshot_data
        if isinstance(snapshot_data, PortfolioSnapshot)
        else PortfolioSnapshot.from_dict(snapshot_data)
    )

    repo: HistoryRepository = history_repo or SqliteHistoryRepository(DEFAULT_DB_PATH)

    try:
        repo.save_snapshot(snapshot)
    except StorageError as e:
        logger.error(f"Failed to write history snapshot: {e}", exception=e)
        return

    logger.success(f"Snapshot successfully saved to database ({DEFAULT_DB_PATH})")

    if backup_to_gdrive:
        db_file: Path = Path(DEFAULT_DB_PATH)
        if db_file.exists():
            trigger_gdrive_backup(db_file)

        history_json: Path = Path("data/history.json")
        if history_json.exists():
            trigger_gdrive_backup(history_json)
