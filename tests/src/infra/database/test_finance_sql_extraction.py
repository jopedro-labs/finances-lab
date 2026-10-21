"""Unit tests for the FinanceSQLExtractor class."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.infra.database.finance_sql_extraction import (
    AssetHistoricalRecord,
    FinanceSQLExtractor,
    PortfolioHistoricalRecord,
)


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """Creates a temporary SQLite database with test schema and seed data."""
    db_file: Path = tmp_path / "test_finances.db"
    connection: sqlite3.Connection = sqlite3.connect(db_file)
    try:
        cursor: sqlite3.Cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                total_value_eur REAL NOT NULL
            );
            """)
        cursor.execute("""
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            );
            """)
        cursor.execute("""
            CREATE TABLE asset_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                value_eur REAL NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots (id),
                FOREIGN KEY (asset_id) REFERENCES assets (id)
            );
            """)

        cursor.execute(
            "INSERT INTO snapshots (date, total_value_eur) VALUES (?, ?)",
            ("2026-01-01", 1000.0),
        )
        cursor.execute(
            "INSERT INTO snapshots (date, total_value_eur) VALUES (?, ?)",
            ("2026-02-01", 1200.0),
        )

        cursor.execute(
            "INSERT INTO assets (ticker, name, type) VALUES (?, ?, ?)",
            ("VWCE.DE", "Vanguard All-World", "ETF"),
        )
        cursor.execute(
            "INSERT INTO assets (ticker, name, type) VALUES (?, ?, ?)",
            ("AAPL", "Apple Inc.", "Stock"),
        )

        cursor.execute(
            "INSERT INTO asset_snapshots "
            "(snapshot_id, asset_id, quantity, value_eur) "
            "VALUES (?, ?, ?, ?)",
            (1, 1, 10.0, 800.0),
        )
        cursor.execute(
            "INSERT INTO asset_snapshots "
            "(snapshot_id, asset_id, quantity, value_eur) "
            "VALUES (?, ?, ?, ?)",
            (1, 2, 2.0, 200.0),
        )
        cursor.execute(
            "INSERT INTO asset_snapshots "
            "(snapshot_id, asset_id, quantity, value_eur) "
            "VALUES (?, ?, ?, ?)",
            (2, 1, 12.0, 960.0),
        )
        cursor.execute(
            "INSERT INTO asset_snapshots "
            "(snapshot_id, asset_id, quantity, value_eur) "
            "VALUES (?, ?, ?, ?)",
            (2, 2, 2.5, 240.0),
        )

        connection.commit()
    finally:
        connection.close()

    return db_file


@pytest.fixture
def empty_db_path(tmp_path: Path) -> Path:
    """Creates a temporary SQLite database with schema but no rows."""
    db_file: Path = tmp_path / "empty_finances.db"
    connection: sqlite3.Connection = sqlite3.connect(db_file)
    try:
        cursor: sqlite3.Cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                total_value_eur REAL NOT NULL
            );
            """)
        cursor.execute("""
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            );
            """)
        cursor.execute("""
            CREATE TABLE asset_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                value_eur REAL NOT NULL
            );
            """)
        connection.commit()
    finally:
        connection.close()

    return db_file


def test_init_accepts_str_path(tmp_path: Path) -> None:
    """Tests initializing FinanceSQLExtractor with string path."""
    db_str: str = str(tmp_path / "str_db.db")
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=db_str)
    assert extractor.db_path == Path(db_str)


def test_fetch_asset_history_success(mock_db_path: Path) -> None:
    """Tests retrieving asset history records from valid database."""
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=mock_db_path)
    records: list[AssetHistoricalRecord] = extractor.fetch_asset_history()

    assert len(records) == 4

    first_record: AssetHistoricalRecord = records[0]
    assert first_record.snapshot_date == "2026-01-01"
    assert first_record.asset_ticker == "AAPL"
    assert first_record.asset_name == "Apple Inc."
    assert first_record.asset_type == "Stock"
    assert first_record.quantity == 2.0
    assert first_record.value_eur == 200.0

    second_record: AssetHistoricalRecord = records[1]
    assert second_record.snapshot_date == "2026-01-01"
    assert second_record.asset_ticker == "VWCE.DE"
    assert second_record.asset_name == "Vanguard All-World"
    assert second_record.asset_type == "ETF"
    assert second_record.quantity == 10.0
    assert second_record.value_eur == 800.0


def test_fetch_asset_history_empty_table(empty_db_path: Path) -> None:
    """Tests returning empty list when database tables have no rows."""
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=empty_db_path)
    records: list[AssetHistoricalRecord] = extractor.fetch_asset_history()
    assert records == []


def test_fetch_asset_history_db_not_found(tmp_path: Path) -> None:
    """Tests returning empty list when database file does not exist."""
    missing_db: Path = tmp_path / "non_existent.db"
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=missing_db)
    records: list[AssetHistoricalRecord] = extractor.fetch_asset_history()

    assert records == []


def test_fetch_portfolio_history_success(mock_db_path: Path) -> None:
    """Tests retrieving portfolio history records from valid database."""
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=mock_db_path)
    records: list[PortfolioHistoricalRecord] = extractor.fetch_portfolio_history()

    assert len(records) == 2
    assert records[0].snapshot_date == "2026-01-01"
    assert records[0].total_value_eur == 1000.0
    assert records[1].snapshot_date == "2026-02-01"
    assert records[1].total_value_eur == 1200.0


def test_fetch_portfolio_history_empty_table(empty_db_path: Path) -> None:
    """Tests returning empty list when portfolio table has no rows."""
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=empty_db_path)
    records: list[PortfolioHistoricalRecord] = extractor.fetch_portfolio_history()
    assert records == []


def test_fetch_portfolio_history_db_not_found(tmp_path: Path) -> None:
    """Tests returning empty list when database file does not exist."""
    missing_db: Path = tmp_path / "non_existent.db"
    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=missing_db)
    records: list[PortfolioHistoricalRecord] = extractor.fetch_portfolio_history()

    assert records == []


def test_fetch_asset_history_alternate_schema(tmp_path: Path) -> None:
    """Tests retrieving asset history using alternate column names
    (timestamp, yahoo_ticker, asset_type)."""
    db_file: Path = tmp_path / "alt_schema.db"
    conn: sqlite3.Connection = sqlite3.connect(db_file)
    try:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY, timestamp TEXT, "
            "total_value_eur REAL);"
        )
        cursor.execute(
            "CREATE TABLE assets (id INTEGER PRIMARY KEY, yahoo_ticker TEXT, "
            "name TEXT, asset_type TEXT);"
        )
        cursor.execute(
            "CREATE TABLE asset_snapshots (id INTEGER PRIMARY KEY, "
            "snapshot_id INTEGER, asset_id INTEGER, quantity REAL, "
            "value_eur REAL);"
        )
        cursor.execute("INSERT INTO snapshots VALUES (1, '2026-08-01', 500.0);")
        cursor.execute(
            "INSERT INTO assets VALUES (1, 'MSFT', 'Microsoft Corp.', 'STOCK');"
        )
        cursor.execute("INSERT INTO asset_snapshots VALUES (1, 1, 1, 2.0, 500.0);")
        conn.commit()
    finally:
        conn.close()

    extractor: FinanceSQLExtractor = FinanceSQLExtractor(db_path=db_file)
    records: list[AssetHistoricalRecord] = extractor.fetch_asset_history()
    assert len(records) == 1
    assert records[0].asset_ticker == "MSFT"
    assert records[0].snapshot_date == "2026-08-01"
