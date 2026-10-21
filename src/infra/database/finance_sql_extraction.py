"""SQL extraction queries for historical portfolio and asset analytics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.infra.database.connection import DEFAULT_DB_PATH, get_db_context
from src.infra.database.schema import initialize_database

_ALLOWED_DATE_COLS: frozenset[str] = frozenset({"date", "timestamp"})
_ALLOWED_TICKER_COLS: frozenset[str] = frozenset({"ticker", "yahoo_ticker"})
_ALLOWED_TYPE_COLS: frozenset[str] = frozenset({"type", "asset_type"})


@dataclass(frozen=True)
class AssetHistoricalRecord:
    """Historical data point for a specific asset snapshot."""

    snapshot_date: str
    asset_ticker: str
    asset_name: str
    asset_type: str
    quantity: float
    value_eur: float


@dataclass(frozen=True)
class PortfolioHistoricalRecord:
    """Historical data point for total portfolio valuation snapshot."""

    snapshot_date: str
    total_value_eur: float


class FinanceSQLExtractor:
    """Extracts historical performance data from finances SQLite database."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        """Initializes extractor with target SQLite database path."""
        self.db_path: Path = Path(db_path)

    @staticmethod
    def _get_column_name(
        cursor: sqlite3.Cursor, table: str, candidates: list[str]
    ) -> str:
        """Resolves existing column name from an allowlisted set of candidates."""
        cursor.execute(f"PRAGMA table_info({table});")  # nosec B608
        existing_cols: set[str] = {row[1] for row in cursor.fetchall()}
        for candidate in candidates:
            if candidate in existing_cols:
                return candidate
        return candidates[0]

    @staticmethod
    def _safe_col(value: str, allowed: frozenset[str]) -> str:
        """Validates a column name against an explicit allowlist."""
        if value not in allowed:
            raise ValueError(f"Column name '{value}' is not in the allowed list.")
        return value

    @staticmethod
    def _resolve_quantity_col(cursor: sqlite3.Cursor) -> str:
        """Determines whether quantity lives in asset_snapshots or assets table."""
        cursor.execute("PRAGMA table_info(asset_snapshots);")  # nosec B608
        ast_cols: set[str] = {row[1] for row in cursor.fetchall()}
        if "quantity" in ast_cols:
            return "ast.quantity"
        return "a.quantity"

    def fetch_asset_history(self) -> list[AssetHistoricalRecord]:
        """Fetches all historical asset snapshot records joined with metadata."""
        if not self.db_path.exists():
            return []

        records: list[AssetHistoricalRecord] = []
        with get_db_context(self.db_path) as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            date_col: str = self._safe_col(
                self._get_column_name(cursor, "snapshots", ["date", "timestamp"]),
                _ALLOWED_DATE_COLS,
            )
            ticker_col: str = self._safe_col(
                self._get_column_name(cursor, "assets", ["ticker", "yahoo_ticker"]),
                _ALLOWED_TICKER_COLS,
            )
            type_col: str = self._safe_col(
                self._get_column_name(cursor, "assets", ["type", "asset_type"]),
                _ALLOWED_TYPE_COLS,
            )
            qty_col: str = self._resolve_quantity_col(cursor)

            query: str = (
                f"SELECT s.{date_col} AS snapshot_date, "  # nosec B608
                f"a.{ticker_col} AS asset_ticker, "
                f"a.name AS asset_name, "
                f"a.{type_col} AS asset_type, "
                f"{qty_col} AS quantity, "
                f"ast.value_eur AS value_eur "
                f"FROM snapshots s "
                f"JOIN asset_snapshots ast ON ast.snapshot_id = s.id "
                f"JOIN assets a ON ast.asset_id = a.id "
                f"ORDER BY s.{date_col} ASC, a.{ticker_col} ASC;"
            )
            cursor.execute(query)
            rows: list[sqlite3.Row] = cursor.fetchall()
            for row in rows:
                records.append(
                    AssetHistoricalRecord(
                        snapshot_date=str(row["snapshot_date"]),
                        asset_ticker=str(row["asset_ticker"]),
                        asset_name=str(row["asset_name"]),
                        asset_type=str(row["asset_type"]),
                        quantity=float(row["quantity"]),
                        value_eur=float(row["value_eur"]),
                    )
                )
        return records

    def fetch_portfolio_history(self) -> list[PortfolioHistoricalRecord]:
        """Fetches all global portfolio valuation snapshot records."""
        if not self.db_path.exists():
            return []

        records: list[PortfolioHistoricalRecord] = []
        with get_db_context(self.db_path) as conn:
            initialize_database(conn)
            cursor: sqlite3.Cursor = conn.cursor()
            date_col = self._safe_col(
                self._get_column_name(cursor, "snapshots", ["date", "timestamp"]),
                _ALLOWED_DATE_COLS,
            )

            cursor.execute("PRAGMA table_info(snapshots)")
            snap_cols = {row["name"] for row in cursor.fetchall()}
            cursor.execute("PRAGMA table_info(assets)")
            asset_cols = {row["name"] for row in cursor.fetchall()}

            has_baseline = "is_baseline" in snap_cols
            has_is_active = "is_active" in asset_cols
            has_quantity = "quantity" in asset_cols

            baseline_clause = (
                "COALESCE(s.is_baseline, 0) = 1" if has_baseline else "0 = 1"
            )
            active_filter = ""
            if has_is_active:
                active_filter += " AND COALESCE(is_active, 1) = 1"
            if has_quantity:
                active_filter += " AND quantity > 0"

            query: str = (
                f"SELECT s.{date_col} AS snapshot_date, "  # nosec B608
                f"s.total_value_eur AS total_value_eur "
                f"FROM snapshots s "
                f"WHERE s.total_value_eur > 0 "
                f"AND ({baseline_clause} OR ("
                f"  SELECT COUNT(*) FROM asset_snapshots sa "
                f"  WHERE sa.snapshot_id = s.id"
                f") = ("
                f"  SELECT COUNT(*) FROM assets WHERE 1=1{active_filter})) "
                f"ORDER BY s.{date_col} ASC;"
            )
            cursor.execute(query)
            rows: list[sqlite3.Row] = cursor.fetchall()
            for row in rows:
                records.append(
                    PortfolioHistoricalRecord(
                        snapshot_date=str(row["snapshot_date"]),
                        total_value_eur=float(row["total_value_eur"]),
                    )
                )
        return records
