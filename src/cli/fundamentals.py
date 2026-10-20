"""CLI command to sync stock and ETF fundamental history into SQLite database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from src.core.analysis import evaluate_etf_quality, evaluate_stock_quality
from src.core.models import Asset, ETFDetails, StockDetails
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import SqliteOpportunityRepository
from src.infra.database.connection import DEFAULT_DB_PATH, get_db_context
from src.infra.database.schema import initialize_database
from src.utils.logger.logger import logger


def sync_stock_fundamentals(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Synchronizes stock fundamental data into the SQLite database."""
    db_path_obj: Path = Path(db_path)
    opportunity_repo: SqliteOpportunityRepository = SqliteOpportunityRepository(
        db_path=db_path_obj
    )
    stock_provider: StockProvider = StockProvider()

    stocks: list[tuple[int, Asset]] = []
    try:
        with get_db_context(str(db_path_obj)) as conn:
            initialize_database(conn)
            cursor: Any = conn.cursor()
            cursor.execute(
                "SELECT id, isin, name, yahoo_ticker, quantity, "
                "average_buy_price, asset_type FROM assets "
                "WHERE UPPER(asset_type) = 'STOCK'"
            )
            rows: list[Any] = cursor.fetchall()
            stocks = [
                (
                    int(row["id"]),
                    Asset(
                        name=str(row["name"]),
                        isin=str(row["isin"] or ""),
                        yahoo_ticker=str(row["yahoo_ticker"]),
                        quantity=float(row["quantity"]),
                        average_buy_price=float(row["average_buy_price"]),
                        asset_type=str(row["asset_type"]),
                    ),
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to fetch stock assets from database: {e}")
        sys.exit(1)

    if not stocks:
        logger.info("No stock assets found in database. Nothing to sync.")
        return

    logger.info(f"Starting fundamental sync for {len(stocks)} stock assets...")

    for asset_id, asset in stocks:
        try:
            logger.info(
                f"Fetching details for ticker '{asset.yahoo_ticker}' "
                f"(asset_id={asset_id})..."
            )
            details: StockDetails | None = stock_provider.get_details(
                asset, force_refresh=True
            )
            if details is None:
                logger.warning(
                    f"No fundamental details returned for ticker "
                    f"'{asset.yahoo_ticker}'. "
                    "Verify provider implementation or network limits."
                )
                continue

            evaluation: dict[str, Any] = evaluate_stock_quality(details)
            quality_tier: str | None = (
                str(evaluation["tier"]) if evaluation.get("tier") is not None else None
            )
            quality_score: int | None = (
                int(evaluation["score"])
                if evaluation.get("score") is not None
                else None
            )

            opportunity_repo.save_stock_fundamentals(
                asset_id=asset_id,
                details=details,
                quality_tier=quality_tier,
                quality_score=quality_score,
            )
            opportunity_repo.upsert_asset_fundamentals(
                asset_id=asset_id,
                asset_type="STOCK",
                details=details,
                quality_tier=quality_tier,
                quality_score=quality_score,
            )
            logger.success(
                f"Successfully synced stock fundamentals for '{asset.yahoo_ticker}'."
            )
        except Exception as e:
            logger.error(
                f"Failed to sync fundamentals for ticker '{asset.yahoo_ticker}': {e}"
            )


def sync_etf_fundamentals(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Synchronizes ETF fundamental data into the SQLite database."""
    db_path_obj: Path = Path(db_path)
    opportunity_repo: SqliteOpportunityRepository = SqliteOpportunityRepository(
        db_path=db_path_obj
    )
    etf_provider: ETFProvider = ETFProvider()

    etfs: list[tuple[int, Asset]] = []
    try:
        with get_db_context(str(db_path_obj)) as conn:
            initialize_database(conn)
            cursor: Any = conn.cursor()
            cursor.execute(
                "SELECT id, isin, name, yahoo_ticker, quantity, "
                "average_buy_price, asset_type FROM assets "
                "WHERE UPPER(asset_type) = 'ETF'"
            )
            rows: list[Any] = cursor.fetchall()
            etfs = [
                (
                    int(row["id"]),
                    Asset(
                        name=str(row["name"]),
                        isin=str(row["isin"] or ""),
                        yahoo_ticker=str(row["yahoo_ticker"]),
                        quantity=float(row["quantity"]),
                        average_buy_price=float(row["average_buy_price"]),
                        asset_type=str(row["asset_type"]),
                    ),
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to fetch ETF assets from database: {e}")
        sys.exit(1)

    if not etfs:
        logger.info("No ETF assets found in database. Nothing to sync.")
        return

    logger.info(f"Starting fundamental sync for {len(etfs)} ETF assets...")

    for asset_id, asset in etfs:
        try:
            logger.info(
                f"Fetching ETF details for ISIN '{asset.isin}' "
                f"(asset_id={asset_id})..."
            )
            details: ETFDetails | None = etf_provider.get_details(
                asset, force_refresh=True
            )
            if details is None:
                logger.warning(
                    f"No fundamental details returned for ETF ISIN '{asset.isin}'. "
                    "Verify provider implementation or network limits."
                )
                continue

            evaluation: dict[str, Any] = evaluate_etf_quality(details)
            quality_tier: str | None = (
                str(evaluation["tier"]) if evaluation.get("tier") is not None else None
            )
            quality_score: int | None = (
                int(evaluation["score"])
                if evaluation.get("score") is not None
                else None
            )

            opportunity_repo.save_etf_fundamentals(
                asset_id=asset_id,
                details=details,
                quality_tier=quality_tier,
                quality_score=quality_score,
            )
            opportunity_repo.upsert_asset_fundamentals(
                asset_id=asset_id,
                asset_type="ETF",
                details=details,
                quality_tier=quality_tier,
                quality_score=quality_score,
            )
            logger.success(f"Successfully synced ETF fundamentals for '{asset.isin}'.")
        except Exception as e:
            logger.error(
                f"Failed to sync fundamentals for ETF ISIN '{asset.isin}': {e}"
            )


def sync_portfolio_fundamentals(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Orchestrates stock and ETF fundamental sync."""
    logger.section("Synchronizing Portfolio Fundamentals")
    sync_stock_fundamentals(db_path=db_path)
    sync_etf_fundamentals(db_path=db_path)


def main() -> None:
    """CLI entrypoint for standalone fundamentals sync execution."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Stock and ETF fundamentals management and history sync."
    )
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser] = (
        parser.add_subparsers(dest="command", required=True)
    )

    sync_parser: argparse.ArgumentParser = subparsers.add_parser(
        "sync", help="Synchronize portfolio fundamentals into database."
    )
    sync_parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite database file.",
    )

    args: argparse.Namespace = parser.parse_args()

    if args.command == "sync":
        sync_portfolio_fundamentals(db_path=args.db_path)


if __name__ == "__main__":
    main()
