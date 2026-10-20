"""Unit tests for data providers in src/core/providers.py covering all stock/ETF price,
extended details, FX conversion fallbacks, cache misses, and exception scenarios.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.core.models import (
    Asset,
    CountryExposure,
    ETFDetails,
    Quotation,
    SectorExposure,
    StockDetails,
)
from src.core.providers import ETFProvider, StockProvider

# ==============================================================================
# StockProvider Tests
# ==============================================================================


@patch("src.core.providers.get_exchange_rate")
@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_usd_converted_to_eur(
    mock_ticker_cls: MagicMock, mock_get_fx: MagicMock
) -> None:
    """Validates StockProvider converts foreign currency to EUR."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {"regularMarketPrice": 150.0, "currency": "USD"}
    mock_ticker_cls.return_value = mock_ticker_inst
    mock_get_fx.return_value = 0.90

    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    provider: StockProvider = StockProvider()
    quote: Quotation | None = provider.get_price(asset)

    assert quote is not None
    assert quote.price == 135.0
    assert quote.currency == "EUR"
    mock_get_fx.assert_called_once_with("USD", "EUR")


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_eur_no_conversion(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider returns EUR price directly without FX conversion."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {"regularMarketPrice": 100.0, "currency": "EUR"}
    mock_ticker_cls.return_value = mock_ticker_inst

    asset: Asset = Asset(
        name="SAP",
        isin="DE0007164600",
        yahoo_ticker="SAP.DE",
        quantity=5.0,
        average_buy_price=90.0,
    )

    provider: StockProvider = StockProvider()
    quote: Quotation | None = provider.get_price(asset)

    assert quote is not None
    assert quote.price == 100.0
    assert quote.currency == "EUR"


def test_stock_provider_get_price_missing_ticker() -> None:
    """Validates get_price returns None when yahoo_ticker is empty."""
    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="No Ticker",
        isin="US0000000000",
        yahoo_ticker="",
        quantity=1.0,
        average_buy_price=10.0,
    )

    assert provider.get_price(asset) is None


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_fallback_to_history(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates get_price falls back to 1d close when info is missing prices."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {"currency": "EUR"}
    mock_df: pd.DataFrame = pd.DataFrame({"Close": [105.5]})
    mock_ticker_inst.history.return_value = mock_df
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="SAP",
        isin="DE0007164600",
        yahoo_ticker="SAP.DE",
        quantity=5.0,
        average_buy_price=90.0,
    )

    quote: Quotation | None = provider.get_price(asset)

    assert quote is not None
    assert quote.price == 105.5
    assert quote.currency == "EUR"


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_no_price_found(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates get_price returns None when no price source contains data."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {}
    mock_ticker_inst.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Unknown",
        isin="XX0000000000",
        yahoo_ticker="UNK",
        quantity=1.0,
        average_buy_price=10.0,
    )

    assert provider.get_price(asset) is None


@patch("src.core.providers.get_exchange_rate")
@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_fx_conversion_failure(
    mock_ticker_cls: MagicMock, mock_get_fx: MagicMock
) -> None:
    """Validates get_price keeps original currency and price if FX rate fetch fails."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {"regularMarketPrice": 150.0, "currency": "USD"}
    mock_ticker_cls.return_value = mock_ticker_inst
    mock_get_fx.return_value = None

    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    provider: StockProvider = StockProvider()
    quote: Quotation | None = provider.get_price(asset)

    assert quote is not None
    assert quote.price == 150.0
    assert quote.currency == "USD"


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_price_exception_handling(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates get_price handles yfinance exceptions cleanly."""
    mock_ticker_cls.side_effect = Exception("API rate limit")

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    assert provider.get_price(asset) is None


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_details_success(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider parses yfinance info dictionary correctly."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {
        "marketCap": 3000000000000.0,
        "trailingPE": 32.5,
        "forwardPE": 28.0,
        "dividendYield": 0.55,
        "fiftyTwoWeekHigh": 235.0,
        "fiftyTwoWeekLow": 165.0,
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    details: StockDetails | None = provider.get_details(asset, force_refresh=True)

    assert details is not None
    assert details.market_cap == 3000000000000.0
    assert details.pe_ratio == 32.5
    assert details.forward_pe == 28.0
    assert details.dividend_yield_pct == 0.55
    assert details.fifty_two_week_high == 235.0
    assert details.fifty_two_week_low == 165.0
    assert details.sector == "Technology"
    assert details.industry == "Consumer Electronics"


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_details_dividend_rate_calculation(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider calculates dividend yield from rate and current price."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {
        "dividendRate": 2.0,
        "currentPrice": 100.0,
    }
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    details: StockDetails | None = provider.get_details(asset, force_refresh=True)

    assert details is not None
    assert details.dividend_yield_pct == 2.0


def test_stock_provider_get_details_missing_ticker() -> None:
    """Validates StockProvider returns None when yahoo_ticker is missing."""
    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="No Ticker",
        isin="US0000000000",
        yahoo_ticker="",
        quantity=1.0,
        average_buy_price=10.0,
    )

    assert provider.get_details(asset) is None


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_details_empty_or_invalid_info(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider handles empty or non-dict info from yfinance."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = None
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    assert provider.get_details(asset, force_refresh=True) is None


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_details_invalid_float_conversion(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider safely ignores non-numeric float fields."""
    mock_ticker_inst: MagicMock = MagicMock()
    mock_ticker_inst.info = {
        "marketCap": "INVALID_NUMBER",
        "trailingPE": "NOT_A_FLOAT",
    }
    mock_ticker_cls.return_value = mock_ticker_inst

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    details: StockDetails | None = provider.get_details(asset, force_refresh=True)

    assert details is not None
    assert details.market_cap is None
    assert details.pe_ratio is None


@patch("src.core.providers.yf.Ticker")
def test_stock_provider_get_details_handles_exception(
    mock_ticker_cls: MagicMock,
) -> None:
    """Validates StockProvider handles network or parsing exceptions gracefully."""
    mock_ticker_cls.side_effect = Exception("Network error")

    provider: StockProvider = StockProvider()
    asset: Asset = Asset(
        name="Apple",
        isin="US0378331005",
        yahoo_ticker="AAPL",
        quantity=10.0,
        average_buy_price=120.0,
    )

    assert provider.get_details(asset, force_refresh=True) is None


# ==============================================================================
# ETFProvider Tests
# ==============================================================================


@patch("src.core.providers.StockProvider.get_price")
def test_etf_provider_get_price(mock_get_price: MagicMock) -> None:
    """Validates ETFProvider delegates get_price directly to StockProvider."""
    mock_get_price.return_value = Quotation(price=100.0, currency="EUR")
    provider: ETFProvider = ETFProvider()

    asset: Asset = Asset(
        name="Core MSCI World",
        isin="IE00B4L5Y983",
        yahoo_ticker="EUNL.DE",
        quantity=5.0,
        average_buy_price=80.0,
    )

    quote: Quotation | None = provider.get_price(asset)

    assert quote is not None
    assert quote.price == 100.0
    mock_get_price.assert_called_once_with(asset)


@patch("src.core.providers.StockProvider.get_price")
def test_etf_provider_uses_cache_hit(mock_get_price: MagicMock) -> None:
    """Validates ETFProvider uses cached ETF composition when present."""
    mock_get_price.return_value = Quotation(price=100.0, currency="EUR")
    mock_cache: MagicMock = MagicMock()
    sample_details: ETFDetails = ETFDetails(
        holdings=[],
        sector_breakdown=[SectorExposure(sector_name="Technology", weight_pct=100.0)],
        country_breakdown=[
            CountryExposure(country_name="United States", weight_pct=100.0)
        ],
        ter_pct=0.20,
    )
    mock_cache.get_etf_details.return_value = sample_details

    mock_client: MagicMock = MagicMock()

    provider: ETFProvider = ETFProvider(
        justetf_client=mock_client, cache_repo=mock_cache
    )
    asset: Asset = Asset(
        name="Core MSCI World",
        isin="IE00B4L5Y983",
        yahoo_ticker="EUNL.DE",
        quantity=5.0,
        average_buy_price=80.0,
    )

    quote: Quotation | None = provider.get_price(asset)
    details: ETFDetails | None = provider.get_details(
        asset, db_path="/nonexistent/test.db"
    )

    assert quote is not None
    assert quote.price == 100.0
    assert details == sample_details
    mock_cache.get_etf_details.assert_called_once_with("IE00B4L5Y983")
    mock_client.get_etf_details.assert_not_called()


def test_etf_provider_cache_miss_fetches_and_saves() -> None:
    """Validates ETFProvider fetches from scraper and caches on cache miss."""
    mock_cache: MagicMock = MagicMock()
    mock_cache.get_etf_details.return_value = None

    sample_details: ETFDetails = ETFDetails(
        holdings=[],
        sector_breakdown=[SectorExposure(sector_name="Technology", weight_pct=100.0)],
        country_breakdown=[
            CountryExposure(country_name="United States", weight_pct=100.0)
        ],
        ter_pct=0.20,
    )
    mock_client: MagicMock = MagicMock()
    mock_client.get_etf_details.return_value = sample_details

    provider: ETFProvider = ETFProvider(
        justetf_client=mock_client, cache_repo=mock_cache
    )
    asset: Asset = Asset(
        name="Core MSCI World",
        isin="IE00B4L5Y983",
        yahoo_ticker="EUNL.DE",
        quantity=5.0,
        average_buy_price=80.0,
    )

    details: ETFDetails | None = provider.get_details(
        asset, db_path="/nonexistent/test.db"
    )

    assert details == sample_details
    mock_client.get_etf_details.assert_called_once_with("IE00B4L5Y983")
    mock_cache.save_etf_details.assert_called_once_with("IE00B4L5Y983", sample_details)


def test_etf_provider_get_details_missing_isin() -> None:
    """Validates ETFProvider returns None when asset ISIN is missing."""
    provider: ETFProvider = ETFProvider()
    asset: Asset = Asset(
        name="No ISIN ETF",
        isin="",
        yahoo_ticker="NOISIN",
        quantity=1.0,
        average_buy_price=10.0,
    )

    assert provider.get_details(asset) is None


def test_etf_provider_get_details_scraper_exception() -> None:
    """Validates ETFProvider handles scraper exceptions gracefully for generic ETFs."""
    mock_cache: MagicMock = MagicMock()
    mock_cache.get_etf_details.return_value = None

    mock_client: MagicMock = MagicMock()
    mock_client.get_etf_details.side_effect = Exception("Scraper network error")

    provider: ETFProvider = ETFProvider(
        justetf_client=mock_client, cache_repo=mock_cache
    )
    asset: Asset = Asset(
        name="Generic Global Bond Fund",
        isin="IE00B1234567",
        yahoo_ticker="BOND.DE",
        quantity=5.0,
        average_buy_price=80.0,
    )

    assert provider.get_details(asset) is None


def test_etf_provider_get_details_scraper_exception_returns_none() -> None:
    """Validates that None is returned when the JustETF scraper fails."""
    mock_cache: MagicMock = MagicMock()
    mock_cache.get_etf_details.return_value = None

    mock_client: MagicMock = MagicMock()
    mock_client.get_etf_details.side_effect = Exception("Scraper network error")

    provider: ETFProvider = ETFProvider(
        justetf_client=mock_client, cache_repo=mock_cache
    )
    asset: Asset = Asset(
        name="Core MSCI World",
        isin="IE00B4L5Y983",
        yahoo_ticker="EUNL.DE",
        quantity=5.0,
        average_buy_price=80.0,
    )

    details: ETFDetails | None = provider.get_details(asset, force_refresh=True)

    assert details is None


@patch("src.core.providers.JustETFClient")
@patch("src.core.providers.JsonETFCacheRepository")
@patch("src.core.providers.StockProvider")
def test_etf_provider_default_instantiation(
    mock_stock_cls: MagicMock,
    mock_cache_cls: MagicMock,
    mock_client_cls: MagicMock,
) -> None:
    """Validates ETFProvider default instantiation when arguments are None."""
    ETFProvider(justetf_client=None, cache_repo=None, stock_provider=None)

    mock_client_cls.assert_called_once()
    mock_cache_cls.assert_called_once()
    mock_stock_cls.assert_called_once()
