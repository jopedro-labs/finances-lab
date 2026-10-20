"""Data provider abstractions and implementations for stocks and ETFs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yfinance as yf  # type: ignore[import-untyped]

from src.core.currency_exchange import get_exchange_rate
from src.core.models import (
    Asset,
    ETFDetails,
    ETFMarketData,
    Quotation,
    StockDetails,
)
from src.core.repositories import (
    ETFCacheRepository,
    JsonETFCacheRepository,
    SqliteOpportunityRepository,
)
from src.infra.database.connection import DEFAULT_DB_PATH
from src.infra.justetf.client import JustETFClient
from src.utils.logger.logger import logger

STOCK_FUNDAMENTALS_TTL_HOURS: int = 24
ETF_FUNDAMENTALS_TTL_HOURS: int = 168  # 7 days


class AssetDataProvider(Protocol):
    """Protocol defining operations for fetching asset price and metadata."""

    def get_price(self, asset: Asset) -> Quotation | None: ...

    def get_details(
        self, asset: Asset, force_refresh: bool = False
    ) -> ETFDetails | StockDetails | None: ...


class StockProvider:
    """Data provider for standard equity/stock assets using yfinance."""

    def get_price(self, asset: Asset) -> Quotation | None:
        if not asset.yahoo_ticker:
            logger.error(f"No Yahoo ticker provided for stock asset '{asset.name}'.")
            return None

        try:
            ticker: yf.Ticker = yf.Ticker(asset.yahoo_ticker)
            info: dict[str, Any] = ticker.info

            price: float | None = (
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
            )

            if not price:
                hist: Any = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])

            if price:
                native_price: float = price
                native_currency: str = str(info.get("currency", "EUR")).upper()
                currency: str = native_currency

                if native_currency != "EUR":
                    rate: float | None = get_exchange_rate(native_currency, "EUR")
                    if rate:
                        price = price * rate
                        currency = "EUR"

                return Quotation(
                    price=price,
                    currency=currency,
                    timestamp=datetime.now(),
                    native_price=native_price,
                    native_currency=native_currency,
                )

            logger.error(f"Could not retrieve price for ticker '{asset.yahoo_ticker}'.")
            return None

        except Exception as e:
            logger.error(f"Error fetching quotation for '{asset.yahoo_ticker}': {e}")
            return None

    def get_details(
        self,
        asset: Asset,
        force_refresh: bool = False,
        db_path: str | Path | None = None,
    ) -> StockDetails | None:
        if not asset.yahoo_ticker:
            logger.error(f"No Yahoo ticker provided for stock asset '{asset.name}'.")
            return None

        # --- TTL cache lookup ---
        cache_repo: SqliteOpportunityRepository | None = None
        asset_id: int | None = None
        resolved_db: Path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        if not force_refresh and resolved_db.exists():
            try:
                from src.infra.database.connection import get_db_context
                from src.infra.database.schema import initialize_database as _init_db

                with get_db_context(str(resolved_db)) as conn:
                    _init_db(conn)
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id FROM assets WHERE yahoo_ticker = ?",
                        (asset.yahoo_ticker,),
                    )
                    row = cur.fetchone()
                    if row:
                        asset_id = int(row["id"])
                if asset_id is not None:
                    cache_repo = SqliteOpportunityRepository(db_path=resolved_db)
                    cached = cache_repo.get_asset_fundamentals(
                        asset_id=asset_id,
                        asset_type="STOCK",
                        ttl_hours=STOCK_FUNDAMENTALS_TTL_HOURS,
                    )
                    if cached is not None and isinstance(cached, StockDetails):
                        logger.info(
                            f"Using cached fundamentals for '{asset.yahoo_ticker}' "
                            f"(asset_id={asset_id})."
                        )
                        return cached
            except Exception as e:
                logger.warning(
                    f"Cache lookup failed for '{asset.yahoo_ticker}', "
                    f"falling back to live fetch: {e}"
                )

        try:
            ticker: yf.Ticker = yf.Ticker(asset.yahoo_ticker)
            info: dict[str, Any] = ticker.info

            if not info or not isinstance(info, dict):
                logger.error(
                    f"yfinance returned empty metadata for '{asset.yahoo_ticker}'."
                )
                return None

            def _parse_float(key: str) -> float | None:
                val: Any = info.get(key)
                if val is None:
                    return None
                try:
                    parsed_val: float = float(val)
                    # Filter out zero or near-zero valuation metrics
                    # returned by yfinance
                    if (
                        key
                        in (
                            "priceToBook",
                            "trailingPE",
                            "forwardPE",
                            "marketCap",
                            "pegRatio",
                            "totalDebtToEquity",
                        )
                        and parsed_val < 0.01
                    ):
                        return None
                    return parsed_val
                except (ValueError, TypeError):
                    return None

            def _parse_pct(key: str) -> float | None:
                val: Any = info.get(key)
                if val is None:
                    return None
                try:
                    return round(float(val) * 100.0, 4)
                except (ValueError, TypeError):
                    return None

            def _parse_str(key: str) -> str | None:
                val: Any = info.get(key)
                return str(val) if val is not None else None

            dividend_rate: float | None = _parse_float("dividendRate") or _parse_float(
                "trailingAnnualDividendRate"
            )
            current_price: float | None = (
                _parse_float("currentPrice")
                or _parse_float("previousClose")
                or _parse_float("regularMarketPrice")
            )

            dividend_yield_pct: float | None = None
            if (
                dividend_rate is not None
                and current_price is not None
                and current_price > 0
            ):
                dividend_yield_pct = round((dividend_rate / current_price) * 100.0, 4)
            else:
                raw_div: float | None = _parse_float("dividendYield")
                if raw_div is not None:
                    dividend_yield_pct = round(raw_div, 4)

            # FCF sanity: yfinance reports financials in financialCurrency (often TWD,
            # JPY, KRW for non-US companies) while the quote currency may be USD/EUR.
            # If they differ, the raw FCF number is in local units and cannot be
            # compared with market-cap/price figures — return None to avoid
            # misleading displays rather than attempt a live FX conversion.
            # The same applies to bookValue per share (used in P/B): when
            # financialCurrency ≠ currency (e.g. TSM: TWD vs USD, ASML: EUR vs USD)
            # the denominator of the P/B ratio is in a different currency than the
            # price, making the ratio meaningless.
            report_currency: str | None = info.get("financialCurrency")
            quote_currency: str | None = info.get("currency")
            currencies_match: bool = (
                report_currency is not None
                and quote_currency is not None
                and report_currency.upper() == quote_currency.upper()
            )
            fcf_raw: float | None = _parse_float("freeCashflow")
            free_cashflow: float | None = fcf_raw if currencies_match else None
            pb_raw: float | None = _parse_float("priceToBook")
            price_to_book: float | None = pb_raw if currencies_match else None

            # Price sanity: if currentPrice deviates >50% from 50D average it is
            # likely a stale/off-hours artefact — fall back to regularMarketPrice.
            fifty_day_avg: float | None = _parse_float("fiftyDayAverage")
            raw_price: float | None = _parse_float("currentPrice") or _parse_float(
                "regularMarketPrice"
            )
            if (
                raw_price is not None
                and fifty_day_avg is not None
                and fifty_day_avg > 0
                and abs(raw_price - fifty_day_avg) / fifty_day_avg > 0.50
            ):
                raw_price = _parse_float("regularMarketPrice") or _parse_float(
                    "previousClose"
                )

            def _parse_int(key: str) -> int | None:
                val: Any = info.get(key)
                if val is None:
                    return None
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None

            result: StockDetails = StockDetails(
                market_cap=_parse_float("marketCap"),
                pe_ratio=_parse_float("trailingPE"),
                forward_pe=_parse_float("forwardPE"),
                dividend_yield_pct=dividend_yield_pct,
                fifty_two_week_high=_parse_float("fiftyTwoWeekHigh"),
                fifty_two_week_low=_parse_float("fiftyTwoWeekLow"),
                fifty_two_week_change_pct=_parse_pct("52WeekChange"),
                fifty_day_average=fifty_day_avg,
                two_hundred_day_average=_parse_float("twoHundredDayAverage"),
                average_volume=_parse_int("averageVolume"),
                sector=_parse_str("sector"),
                industry=_parse_str("industry"),
                country=_parse_str("country"),
                price_to_book=price_to_book,
                peg_ratio=_parse_float("pegRatio"),
                beta=_parse_float("beta"),
                profit_margins_pct=_parse_pct("profitMargins"),
                gross_margins_pct=_parse_pct("grossMargins"),
                operating_margins_pct=_parse_pct("operatingMargins"),
                revenue_growth_pct=_parse_pct("revenueGrowth"),
                earnings_growth_pct=_parse_pct("earningsGrowth"),
                return_on_equity_pct=_parse_pct("returnOnEquity"),
                return_on_assets_pct=_parse_pct("returnOnAssets"),
                total_debt_to_equity=_parse_float("debtToEquity"),
                free_cashflow=free_cashflow,
                short_ratio=_parse_float("shortRatio"),
                target_mean_price=_parse_float("targetMeanPrice"),
                target_high_price=_parse_float("targetHighPrice"),
                target_low_price=_parse_float("targetLowPrice"),
                number_of_analyst_opinions=_parse_int("numberOfAnalystOpinions"),
                recommendation_key=_parse_str("recommendationKey"),
                eps_trailing_ttm=_parse_float("trailingEps"),
                eps_forward=_parse_float("forwardEps"),
                currency=_parse_str("currency"),
            )

            # Write back to cache if we have a known asset_id
            if cache_repo is not None and asset_id is not None:
                try:
                    cache_repo.upsert_asset_fundamentals(
                        asset_id=asset_id,
                        asset_type="STOCK",
                        details=result,
                    )
                except Exception as cache_err:
                    logger.warning(
                        f"Failed to populate fundamentals cache for "
                        f"'{asset.yahoo_ticker}': {cache_err}"
                    )

            return result
        except Exception as e:
            err_details: str = f"{type(e).__name__} - {e}"
            logger.error(
                f"yfinance exception while fetching '{asset.yahoo_ticker}': "
                f"{err_details}"
            )
            return None


class ETFProvider:
    """Hybrid provider for ETFs combining yfinance and JustETF metadata."""

    def __init__(
        self,
        justetf_client: JustETFClient | None = None,
        cache_repo: ETFCacheRepository | None = None,
        stock_provider: StockProvider | None = None,
    ) -> None:
        self.justetf_client: JustETFClient = justetf_client or JustETFClient()
        self.cache_repo: ETFCacheRepository = cache_repo or JsonETFCacheRepository()
        self._stock_provider: StockProvider = stock_provider or StockProvider()

    def get_price(self, asset: Asset) -> Quotation | None:
        return self._stock_provider.get_price(asset)

    def get_market_data(self, asset: Asset) -> ETFMarketData | None:
        if not asset.yahoo_ticker:
            logger.error(f"No Yahoo ticker provided for ETF asset '{asset.name}'.")
            return None
        try:
            info: dict[str, Any] = yf.Ticker(asset.yahoo_ticker).info
            if not info or not isinstance(info, dict):
                return None

            def _float(key: str) -> float | None:
                val: Any = info.get(key)
                try:
                    return float(val) if val is not None else None
                except (ValueError, TypeError):
                    return None

            def _int(key: str) -> int | None:
                val: Any = info.get(key)
                try:
                    return int(val) if val is not None else None
                except (ValueError, TypeError):
                    return None

            price: float | None = (
                _float("regularMarketPrice")
                or _float("currentPrice")
                or _float("previousClose")
            )
            currency: str | None = (
                str(info.get("currency", "EUR")).upper()
                if info.get("currency")
                else None
            )

            return ETFMarketData(
                price=price,
                currency=currency,
                nav_price=_float("navPrice"),
                fifty_two_week_high=_float("fiftyTwoWeekHigh"),
                fifty_two_week_low=_float("fiftyTwoWeekLow"),
                fifty_two_week_change_pct=_float("fiftyTwoWeekChangePercent"),
                fifty_day_average=_float("fiftyDayAverage"),
                two_hundred_day_average=_float("twoHundredDayAverage"),
                average_volume=_int("averageVolume"),
            )
        except Exception as e:
            logger.error(f"Error fetching market data for '{asset.yahoo_ticker}': {e}")
            return None

    def get_details(
        self,
        asset: Asset,
        force_refresh: bool = False,
        db_path: str | Path | None = None,
    ) -> ETFDetails | None:
        """Retrieves ETF composition from JustETF, returning None if unavailable.

        Checks the SQLite asset_fundamentals cache first (7-day TTL) before
        hitting JustETF.
        """
        if not asset.isin:
            logger.error(f"No ISIN provided for ETF asset {asset.name}.")
            return None

        # --- SQLite TTL cache lookup ---
        resolved_db: Path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        if not force_refresh and resolved_db.exists():
            try:
                from src.infra.database.connection import get_db_context
                from src.infra.database.schema import initialize_database as _init_db

                asset_id: int | None = None
                with get_db_context(str(resolved_db)) as conn:
                    _init_db(conn)
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id FROM assets WHERE isin = ?",
                        (asset.isin,),
                    )
                    row = cur.fetchone()
                    if row:
                        asset_id = int(row["id"])
                if asset_id is not None:
                    db_cache_repo = SqliteOpportunityRepository(db_path=resolved_db)
                    db_cached = db_cache_repo.get_asset_fundamentals(
                        asset_id=asset_id,
                        asset_type="ETF",
                        ttl_hours=ETF_FUNDAMENTALS_TTL_HOURS,
                    )
                    if db_cached is not None and isinstance(db_cached, ETFDetails):
                        logger.info(
                            f"Using cached fundamentals for ETF '{asset.isin}' "
                            f"(asset_id={asset_id})."
                        )
                        return db_cached
            except Exception as e:
                logger.warning(
                    f"DB cache lookup failed for ETF '{asset.isin}', "
                    f"falling back to JustETF fetch: {e}"
                )

        # --- JSON file cache (existing TTL) ---
        if not force_refresh:
            cached_details: ETFDetails | None = self.cache_repo.get_etf_details(
                asset.isin
            )
            if cached_details is not None:
                return cached_details

        try:
            details: ETFDetails = self.justetf_client.get_etf_details(asset.isin)
            self.cache_repo.save_etf_details(asset.isin, details)
            return details
        except Exception as e:
            logger.warning(
                f"Failed to fetch ETF details for {asset.name} ({asset.isin}): {e}"
            )
            return None
