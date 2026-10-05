"""Repository protocols and storage implementations (JSON, SQLite, and Parquet) for
portfolio, history, and ETF cache data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from src.config import DEFAULT_ETF_CACHE_TTL_DAYS, ETF_CACHE_FILE
from src.core.exceptions import StorageReadError, StorageWriteError
from src.core.models import (
    Asset,
    AssetSnapshot,
    ETFDetails,
    PortfolioSnapshot,
    StockDetails,
)
from src.infra.database.connection import DEFAULT_DB_PATH, get_db_context
from src.infra.database.schema import initialize_database
from src.utils.logger.logger import logger


class PortfolioRepository(Protocol):
    """Protocol defining operations for reading portfolio configuration."""

    def load_assets(self) -> list[Asset]:
        """Loads all configured assets from storage."""
        ...


class HistoryRepository(Protocol):
    """Protocol defining operations for portfolio history persistence."""

    def load_history(self) -> list[PortfolioSnapshot]:
        """Loads all recorded portfolio snapshots from storage."""
        ...

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Saves a new portfolio snapshot to storage."""
        ...


class ETFCacheRepository(Protocol):
    """Protocol defining operations for caching ETF metadata."""

    def get_etf_details(self, isin: str) -> ETFDetails | None:
        """Retrieves cached ETF details for a given ISIN if available and valid."""
        ...

    def save_etf_details(self, isin: str, details: ETFDetails) -> None:
        """Saves or updates ETF details in the cache."""
        ...


class SqlitePortfolioRepository:
    """SQLite database-backed implementation of PortfolioRepository."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path: Path = Path(db_path)

    def load_assets(self) -> list[Asset]:
        """Loads all portfolio assets from the SQLite database."""
        if not self.db_path.exists():
            return []

        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT isin, name, yahoo_ticker, quantity, "
                    "average_buy_price, asset_type FROM assets ORDER BY id ASC"
                )
                rows = cursor.fetchall()
                return [
                    Asset(
                        name=str(row["name"]),
                        isin=str(row["isin"] or ""),
                        yahoo_ticker=str(row["yahoo_ticker"]),
                        quantity=float(row["quantity"]),
                        average_buy_price=float(row["average_buy_price"]),
                        asset_type=str(row["asset_type"]),
                    )
                    for row in rows
                ]
        except Exception as e:
            raise StorageReadError(
                f"Failed to read portfolio assets from '{self.db_path}': {e}"
            ) from e

    def save_assets(self, assets: list[Asset]) -> None:
        """Saves or updates portfolio assets in the SQLite database."""
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                for asset in assets:
                    cursor.execute(
                        """
                        INSERT INTO assets (
                            isin, name, yahoo_ticker, quantity,
                            average_buy_price, asset_type
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(isin) DO UPDATE SET
                            name=excluded.name,
                            yahoo_ticker=excluded.yahoo_ticker,
                            quantity=excluded.quantity,
                            average_buy_price=excluded.average_buy_price,
                            asset_type=excluded.asset_type;
                        """,
                        (
                            asset.isin if asset.isin else None,
                            asset.name,
                            asset.yahoo_ticker,
                            asset.quantity,
                            asset.average_buy_price,
                            asset.asset_type,
                        ),
                    )
        except Exception as e:
            raise StorageWriteError(
                f"Failed to save assets to '{self.db_path}': {e}"
            ) from e


class SqliteHistoryRepository:
    """SQLite database-backed implementation of HistoryRepository."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path: Path = Path(db_path)

    def load_history(self) -> list[PortfolioSnapshot]:
        """Loads all recorded portfolio snapshots from the SQLite database."""
        if not self.db_path.exists():
            return []

        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, timestamp, total_value_eur FROM snapshots "
                    "ORDER BY id ASC"
                )
                snapshots_rows = cursor.fetchall()
                snapshots: list[PortfolioSnapshot] = []

                for s_row in snapshots_rows:
                    snapshot_id: int = s_row["id"]
                    cursor.execute(
                        """
                        SELECT a.name, a.isin, a.yahoo_ticker,
                               sa.native_price, sa.native_currency, sa.value_eur
                        FROM asset_snapshots sa
                        JOIN assets a ON sa.asset_id = a.id
                        WHERE sa.snapshot_id = ?
                        ORDER BY sa.id ASC
                        """,
                        (snapshot_id,),
                    )
                    asset_rows = cursor.fetchall()
                    asset_snaps: list[AssetSnapshot] = [
                        AssetSnapshot(
                            name=str(a_row["name"]),
                            isin=str(a_row["isin"] or ""),
                            yahoo_ticker=str(a_row["yahoo_ticker"]),
                            native_price=float(a_row["native_price"]),
                            native_currency=str(a_row["native_currency"]),
                            value_eur=float(a_row["value_eur"]),
                        )
                        for a_row in asset_rows
                    ]

                    snapshots.append(
                        PortfolioSnapshot(
                            timestamp=str(s_row["timestamp"]),
                            total_value_eur=float(s_row["total_value_eur"]),
                            assets_snapshot=asset_snaps,
                        )
                    )
                return snapshots
        except Exception as e:
            raise StorageReadError(
                f"Failed to read history from '{self.db_path}': {e}"
            ) from e

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Saves a new portfolio snapshot into the SQLite database."""
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()

                cursor.execute(
                    "INSERT INTO snapshots (timestamp, total_value_eur) "
                    "VALUES (?, ?)",
                    (snapshot.timestamp, snapshot.total_value_eur),
                )
                if cursor.lastrowid is None:
                    raise StorageWriteError("Failed to retrieve inserted snapshot ID.")
                snapshot_id: int = cursor.lastrowid

                for asset_snap in snapshot.assets_snapshot:
                    cursor.execute(
                        "SELECT id FROM assets WHERE yahoo_ticker = ?",
                        (asset_snap.yahoo_ticker,),
                    )
                    row = cursor.fetchone()
                    if row:
                        asset_id: int = row["id"]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO assets (
                                isin, name, yahoo_ticker, quantity,
                                average_buy_price, asset_type
                            )
                            VALUES (?, ?, ?, 0.0, 0.0, 'stock')
                            """,
                            (
                                asset_snap.isin if asset_snap.isin else None,
                                asset_snap.name,
                                asset_snap.yahoo_ticker,
                            ),
                        )
                        if cursor.lastrowid is None:
                            raise StorageWriteError(
                                "Failed to retrieve inserted asset ID."
                            )
                        asset_id = cursor.lastrowid

                    cursor.execute(
                        """
                        INSERT INTO asset_snapshots (
                            snapshot_id, asset_id, native_price,
                            native_currency, value_eur
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            asset_id,
                            asset_snap.native_price,
                            asset_snap.native_currency,
                            asset_snap.value_eur,
                        ),
                    )
        except Exception as e:
            raise StorageWriteError(
                f"Failed to save snapshot to '{self.db_path}': {e}"
            ) from e


class ParquetHistoryRepository:
    """Parquet file-backed implementation of HistoryRepository using PyArrow."""

    def __init__(self, file_path: str | Path = "data/history.parquet") -> None:
        self.file_path: Path = Path(file_path)

    def load_history(self) -> list[PortfolioSnapshot]:
        """Loads all recorded portfolio snapshots from the Parquet file."""
        if not self.file_path.exists():
            return []

        try:
            df: pd.DataFrame = pd.read_parquet(str(self.file_path))
            snapshots: list[PortfolioSnapshot] = []
            for _, row in df.iterrows():
                raw_data: dict[str, Any] = json.loads(str(row["snapshot_json"]))
                snapshots.append(PortfolioSnapshot.from_dict(raw_data))
            return snapshots
        except Exception as e:
            raise StorageReadError(
                f"Failed to read history from Parquet '{self.file_path}': {e}"
            ) from e

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Appends a new portfolio snapshot to the Parquet file."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            record: dict[str, Any] = {
                "timestamp": snapshot.timestamp,
                "total_value_eur": snapshot.total_value_eur,
                "snapshot_json": json.dumps(snapshot.to_dict()),
            }
            df_new: pd.DataFrame = pd.DataFrame([record])
            if self.file_path.exists():
                df_new.to_parquet(
                    str(self.file_path), engine="fastparquet", append=True, index=False
                )
            else:
                df_new.to_parquet(str(self.file_path), index=False)
        except Exception as e:
            raise StorageWriteError(
                f"Failed to write history to Parquet '{self.file_path}': {e}"
            ) from e


class JsonPortfolioRepository:
    """JSON file-based implementation of PortfolioRepository."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path: Path = Path(file_path)

    def load_assets(self) -> list[Asset]:
        """Loads assets from a local JSON portfolio file."""
        if not self.file_path.exists():
            raise StorageReadError(f"Portfolio file not found at '{self.file_path}'.")

        try:
            with open(self.file_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
                return [Asset.from_dict(item) for item in data.get("assets", [])]
        except (json.JSONDecodeError, OSError) as e:
            raise StorageReadError(
                f"Failed to read portfolio from '{self.file_path}': {e}"
            ) from e


class JsonHistoryRepository:
    """JSON file-based implementation of HistoryRepository."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path: Path = Path(file_path)

    def load_history(self) -> list[PortfolioSnapshot]:
        """Loads history snapshots from a local JSON file."""
        if not self.file_path.exists():
            return []

        try:
            with open(self.file_path, encoding="utf-8") as f:
                data: list[dict[str, Any]] = json.load(f)
                return [PortfolioSnapshot.from_dict(item) for item in data]
        except (json.JSONDecodeError, OSError) as e:
            raise StorageReadError(
                f"Failed to read history from '{self.file_path}': {e}"
            ) from e

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Appends a snapshot to the local JSON history file."""
        history: list[PortfolioSnapshot] = self.load_history()
        history.append(snapshot)

        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                raw_data: list[dict[str, Any]] = [s.to_dict() for s in history]
                json.dump(raw_data, f, indent=2)
        except OSError as e:
            raise StorageWriteError(
                f"Failed to write history to '{self.file_path}': {e}"
            ) from e


class JsonETFCacheRepository:
    """JSON file-based implementation of ETFCacheRepository with TTL validation."""

    def __init__(
        self,
        file_path: str | Path = ETF_CACHE_FILE,
        ttl_days: int = DEFAULT_ETF_CACHE_TTL_DAYS,
    ) -> None:
        self.file_path: Path = Path(file_path)
        self.ttl_days: int = ttl_days

    def get_etf_details(self, isin: str) -> ETFDetails | None:
        """Retrieves cached ETF details for an ISIN if unexpired and valid."""
        if not self.file_path.exists():
            return None

        try:
            with open(self.file_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                f"Corrupted or unreadable ETF cache file at " f"'{self.file_path}': {e}"
            )
            return None

        entry: dict[str, Any] | None = data.get(isin)
        if not entry or not isinstance(entry, dict):
            return None

        cached_at_str: str | None = entry.get("cached_at")
        raw_details: Any = entry.get("details")

        if not cached_at_str or not isinstance(raw_details, dict):
            return None

        try:
            cached_at = datetime.fromisoformat(cached_at_str)
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)

            now = datetime.now(UTC)
            age_days = (now - cached_at).total_seconds() / 86400.0

            if age_days > self.ttl_days:
                logger.info(
                    f"Cache entry for ISIN {isin} expired "
                    f"({age_days:.1f} days old)."
                )
                return None

            return ETFDetails.from_dict(raw_details)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse cached ETF details for ISIN {isin}: {e}")
            return None

    def save_etf_details(self, isin: str, details: ETFDetails) -> None:
        """Persists ETF details into the JSON cache file with current timestamp."""
        cache_data: dict[str, Any] = {}

        if self.file_path.exists():
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    cache_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                cache_data = {}

        cache_data[isin] = {
            "cached_at": datetime.now(UTC).isoformat(),
            "details": details.to_dict(),
        }

        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except OSError as e:
            raise StorageWriteError(
                f"Failed to write ETF cache to '{self.file_path}': {e}"
            ) from e


class SqliteOpportunityRepository:
    """SQLite database-backed implementation for persisting and querying
    opportunity evaluation reports."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path: Path = Path(db_path)

    def save_opportunity_report(
        self,
        timestamp: str,
        total_value_eur: float,
        has_ai: bool,
        ranked_scores: list[Any],
        asset_dict_map: dict[str, dict[str, Any]],
        recommendations_map: dict[str, Any],
        advisories_map: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Saves a complete opportunity evaluation run and its asset metrics
        into SQLite.
        """
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO opportunities (timestamp, total_value_eur, has_ai)
                    VALUES (?, ?, ?)
                    ON CONFLICT(timestamp) DO NOTHING;
                    """,
                    (timestamp, total_value_eur, 1 if has_ai else 0),
                )

                cursor.execute(
                    "SELECT id FROM opportunities WHERE timestamp = ?", (timestamp,)
                )
                row = cursor.fetchone()
                if not row:
                    return
                opportunity_id: int = int(row["id"])

                for rank, score in enumerate(ranked_scores, start=1):
                    symbol: str = str(score.symbol)
                    target_item: dict[str, Any] = asset_dict_map.get(symbol, {})
                    rec = recommendations_map.get(symbol)

                    adv_dict = (advisories_map or {}).get(symbol)
                    advisory_json_str: str | None = (
                        __import__("json").dumps(adv_dict) if adv_dict else None
                    )

                    cursor.execute(
                        """
                        INSERT INTO opportunity_asset_metrics (
                            opportunity_id, symbol, asset_type, rank, price_eur,
                            current_allocation_pct, target_allocation_pct,
                            dip_score, cost_score, gap_score, quant_score,
                            ai_action, ai_urgency, ai_confidence_pct,
                            forward_pe, trailing_pe, peg_ratio, price_to_book,
                            dividend_yield_pct, ter, advisory_json
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            opportunity_id,
                            symbol,
                            str(score.asset_type.value).upper(),
                            rank,
                            float(target_item.get("current_price", 0.0)),
                            float(target_item.get("current_allocation_pct", 0.0)),
                            float(target_item.get("target_allocation_pct", 0.0)),
                            float(score.dip_score),
                            float(score.cost_score),
                            float(score.allocation_score),
                            float(score.total_score),
                            (str(rec.action.value) if rec and rec.action else None),
                            (
                                str(rec.urgency_level.value)
                                if rec and rec.urgency_level
                                else None
                            ),
                            (float(rec.confidence_score * 100.0) if rec else None),
                            target_item.get("forward_pe"),
                            target_item.get("trailing_pe"),
                            target_item.get("peg_ratio"),
                            target_item.get("price_to_book"),
                            target_item.get("dividend_yield_pct"),
                            target_item.get("ter"),
                            advisory_json_str,
                        ),
                    )
        except Exception as e:
            raise StorageWriteError(
                f"Failed to save opportunity report to SQLite: {e}"
            ) from e

    def load_asset_history(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        """Loads historical opportunity metrics for a specific asset to enable
        trend analysis.
        """
        if not self.db_path.exists():
            return []

        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT o.timestamp, oam.rank, oam.price_eur, oam.quant_score,
                           oam.forward_pe, oam.dividend_yield_pct, oam.ai_action
                    FROM opportunity_asset_metrics oam
                    JOIN opportunities o ON oam.opportunity_id = o.id
                    WHERE oam.symbol = ?
                    ORDER BY o.timestamp DESC
                    LIMIT ?
                    """,
                    (symbol, limit),
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"Failed to load asset history for '{symbol}': {e}")
            return []

    def load_latest_top_opportunities(self, limit: int = 5) -> list[dict[str, Any]]:
        """Loads the top-N ranked assets from the most recent opportunity run."""
        if not self.db_path.exists():
            return []
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT oam.symbol, oam.asset_type, oam.rank,
                           oam.price_eur, oam.quant_score, oam.ai_action
                    FROM opportunity_asset_metrics oam
                    JOIN opportunities o ON oam.opportunity_id = o.id
                    WHERE o.id = (SELECT MAX(id) FROM opportunities)
                    ORDER BY oam.rank ASC
                    LIMIT ?
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to load top opportunities: {e}")
            return []

    def save_stock_fundamentals(
        self,
        asset_id: int,
        details: StockDetails,
        quality_tier: str | None = None,
        quality_score: int | None = None,
    ) -> None:
        """Inserts a historical fundamental data snapshot for a specific stock asset.

        Args:
            asset_id: Database primary key of the asset in the assets table.
            details: Stock details object containing fundamental metrics.
            quality_tier: Evaluated absolute quality tier (e.g., Tier A).
            quality_score: Evaluated absolute quality score (0-100).
        """
        query: str = """
            INSERT INTO stock_fundamental_history (
                asset_id,
                fetched_at,
                market_cap,
                pe_ratio,
                forward_pe,
                dividend_yield_pct,
                fifty_two_week_high,
                fifty_two_week_low,
                sector,
                industry,
                quality_tier,
                quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        fetched_at_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params: tuple[
            int,
            str,
            float | None,
            float | None,
            float | None,
            float | None,
            float | None,
            float | None,
            str | None,
            str | None,
            str | None,
            int | None,
        ] = (
            asset_id,
            fetched_at_str,
            details.market_cap,
            details.pe_ratio,
            details.forward_pe,
            details.dividend_yield_pct,
            details.fifty_two_week_high,
            details.fifty_two_week_low,
            details.sector,
            details.industry,
            quality_tier,
            quality_score,
        )

        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(query, params)

            logger.success(
                "Successfully saved fundamental history snapshot for "
                f"asset_id={asset_id} with quality tier {quality_tier}."
            )
        except Exception as e:
            raise StorageWriteError(
                f"Failed to save stock fundamentals to '{self.db_path}': {e}"
            ) from e

    def save_etf_fundamentals(
        self,
        asset_id: int,
        details: ETFDetails,
        quality_tier: str | None = None,
        quality_score: int | None = None,
    ) -> None:
        """Persists an ETF fundamental snapshot record into SQLite history.

        Args:
            asset_id: Database identifier of the ETF asset.
            details: ETF details containing TER, holdings, and breakdowns.
            quality_tier: Evaluated absolute quality tier (e.g., Tier A).
            quality_score: Evaluated absolute quality score (0-100).
        """
        query: str = """
            INSERT INTO etf_fundamental_history (
                asset_id,
                fetched_at,
                ter_pct,
                holdings_json,
                sector_breakdown_json,
                country_breakdown_json,
                quality_tier,
                quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        fetched_at_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        holdings_data: list[dict[str, Any]] = (
            [h.to_dict() for h in details.holdings] if details.holdings else []
        )
        sector_data: list[dict[str, Any]] = (
            [s.to_dict() for s in details.sector_breakdown]
            if details.sector_breakdown
            else []
        )
        country_data: list[dict[str, Any]] = (
            [c.to_dict() for c in details.country_breakdown]
            if details.country_breakdown
            else []
        )

        params: tuple[
            int,
            str,
            float | None,
            str,
            str,
            str,
            str | None,
            int | None,
        ] = (
            asset_id,
            fetched_at_str,
            details.ter_pct,
            json.dumps(holdings_data),
            json.dumps(sector_data),
            json.dumps(country_data),
            quality_tier,
            quality_score,
        )

        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(query, params)

            logger.success(
                "Successfully saved ETF fundamental history snapshot for "
                f"asset_id={asset_id} with quality tier {quality_tier}."
            )
        except Exception as e:
            raise StorageWriteError(
                f"Failed to save ETF fundamentals to '{self.db_path}': {e}"
            ) from e
