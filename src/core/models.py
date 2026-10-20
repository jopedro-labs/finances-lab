"""
Domain models for the finances application.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class Quotation:
    """Represents a market quotation for a ticker."""

    price: float
    currency: str
    timestamp: datetime = field(default_factory=datetime.now)
    native_price: float | None = None
    native_currency: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "currency": self.currency,
            "timestamp": self.timestamp.isoformat(),
            "native_price": self.native_price,
            "native_currency": self.native_currency,
        }


@dataclass(frozen=True, slots=True)
class Asset:
    """Represents an asset in the user's portfolio configuration."""

    name: str
    isin: str
    yahoo_ticker: str
    quantity: float
    average_buy_price: float
    asset_type: str = "STOCK"
    xtb_ticker: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Asset:
        raw_type: str = str(
            data.get("asset_type") or data.get("type") or "STOCK"
        ).upper()
        return cls(
            name=str(data.get("name", "")),
            isin=str(data.get("isin", "")),
            yahoo_ticker=str(data.get("yahoo_ticker") or data.get("symbol", "")),
            quantity=float(data.get("quantity", 0.0)),
            average_buy_price=float(
                data.get("averageBuyPrice", data.get("average_buy_price", 0.0))
            ),
            asset_type=raw_type,
            xtb_ticker=str(data["xtb_ticker"]) if data.get("xtb_ticker") else None,
        )

    @property
    def acquisition_cost(self) -> float:
        return self.quantity * self.average_buy_price


@dataclass(frozen=True, slots=True)
class AssetSnapshot:
    """Represents the valuation of an asset at a specific point in time."""

    name: str
    isin: str
    yahoo_ticker: str
    native_price: float
    native_currency: str
    value_eur: float

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetSnapshot:
        return cls(
            name=str(data.get("name", "")),
            isin=str(data.get("isin", "")),
            yahoo_ticker=str(data.get("yahoo_ticker", "")),
            native_price=float(data.get("native_price", 0.0)),
            native_currency=str(data.get("native_currency", "EUR")),
            value_eur=float(data.get("value_eur", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Represents a complete portfolio valuation snapshot."""

    timestamp: str
    total_value_eur: float
    assets_snapshot: list[AssetSnapshot]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioSnapshot:
        return cls(
            timestamp=str(data.get("timestamp", "")),
            total_value_eur=float(data.get("total_value_eur", 0.0)),
            assets_snapshot=[
                AssetSnapshot.from_dict(item)
                for item in data.get("assets_snapshot", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_value_eur": self.total_value_eur,
            "assets_snapshot": [item.to_dict() for item in self.assets_snapshot],
        }


@dataclass(frozen=True, slots=True)
class Holding:
    """Represents an individual stock or asset holding within an ETF."""

    name: str
    isin: str
    ticker: str | None
    weight_pct: float

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Holding:
        return cls(
            name=str(data.get("name", "")),
            isin=str(data.get("isin", "")),
            ticker=data.get("ticker"),
            weight_pct=float(data.get("weight_pct", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SectorExposure:
    """Represents sector breakdown weight within an ETF."""

    sector_name: str
    weight_pct: float

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorExposure:
        return cls(
            sector_name=str(data.get("sector_name", "")),
            weight_pct=float(data.get("weight_pct", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CountryExposure:
    """Represents country breakdown weight within an ETF."""

    country_name: str
    weight_pct: float

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CountryExposure:
        return cls(
            country_name=str(data.get("country_name", "")),
            weight_pct=float(data.get("weight_pct", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ETFMarketData:
    """Market data for an ETF fetched from Yahoo Finance."""

    price: float | None = None
    currency: str | None = None
    nav_price: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    fifty_two_week_change_pct: float | None = None
    fifty_day_average: float | None = None
    two_hundred_day_average: float | None = None
    average_volume: int | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class ETFDetails:
    """Consolidates ETF holdings, sector exposure, country exposure,
    and fund metadata."""

    holdings: list[Holding]
    sector_breakdown: list[SectorExposure]
    country_breakdown: list[CountryExposure]
    ter_pct: float | None = None
    inception_date: str | None = None
    fund_size_eur_m: float | None = None
    holdings_count: int | None = None
    replication: str | None = None
    distribution_policy: str | None = None
    index_name: str | None = None
    fund_currency: str | None = None
    volatility_1y_pct: float | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ETFDetails:
        raw_ter: Any = data.get("ter_pct")
        ter_pct: float | None = float(raw_ter) if raw_ter is not None else None
        raw_fund_size: Any = data.get("fund_size_eur_m")
        fund_size: float | None = (
            float(raw_fund_size) if raw_fund_size is not None else None
        )
        raw_hcount: Any = data.get("holdings_count")
        holdings_count: int | None = int(raw_hcount) if raw_hcount is not None else None
        raw_vol: Any = data.get("volatility_1y_pct")
        volatility: float | None = float(raw_vol) if raw_vol is not None else None

        return cls(
            holdings=[Holding.from_dict(item) for item in data.get("holdings", [])],
            sector_breakdown=[
                SectorExposure.from_dict(item)
                for item in data.get("sector_breakdown", [])
            ],
            country_breakdown=[
                CountryExposure.from_dict(item)
                for item in data.get("country_breakdown", [])
            ],
            ter_pct=ter_pct,
            inception_date=data.get("inception_date"),
            fund_size_eur_m=fund_size,
            holdings_count=holdings_count,
            replication=data.get("replication"),
            distribution_policy=data.get("distribution_policy"),
            index_name=data.get("index_name"),
            fund_currency=data.get("fund_currency"),
            volatility_1y_pct=volatility,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "holdings": [item.to_dict() for item in self.holdings],
            "sector_breakdown": [item.to_dict() for item in self.sector_breakdown],
            "country_breakdown": [item.to_dict() for item in self.country_breakdown],
            "ter_pct": self.ter_pct,
            "inception_date": self.inception_date,
            "fund_size_eur_m": self.fund_size_eur_m,
            "holdings_count": self.holdings_count,
            "replication": self.replication,
            "distribution_policy": self.distribution_policy,
            "index_name": self.index_name,
            "fund_currency": self.fund_currency,
            "volatility_1y_pct": self.volatility_1y_pct,
        }


@dataclass(frozen=True, slots=True)
class StockDetails:
    """Consolidates stock fundamental metrics and market data."""

    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    dividend_yield_pct: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    fifty_two_week_change_pct: float | None = None
    fifty_day_average: float | None = None
    two_hundred_day_average: float | None = None
    average_volume: int | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    price_to_book: float | None = None
    peg_ratio: float | None = None
    beta: float | None = None
    profit_margins_pct: float | None = None
    gross_margins_pct: float | None = None
    operating_margins_pct: float | None = None
    revenue_growth_pct: float | None = None
    earnings_growth_pct: float | None = None
    return_on_equity_pct: float | None = None
    return_on_assets_pct: float | None = None
    total_debt_to_equity: float | None = None
    free_cashflow: float | None = None
    short_ratio: float | None = None
    target_mean_price: float | None = None
    target_high_price: float | None = None
    target_low_price: float | None = None
    number_of_analyst_opinions: int | None = None
    recommendation_key: str | None = None
    eps_trailing_ttm: float | None = None
    eps_forward: float | None = None
    currency: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StockDetails:
        def _get_float(key: str) -> float | None:
            val: Any = data.get(key)
            return float(val) if val is not None else None

        def _get_int(key: str) -> int | None:
            val: Any = data.get(key)
            return int(val) if val is not None else None

        def _get_str(key: str) -> str | None:
            val: Any = data.get(key)
            return str(val) if val is not None else None

        return cls(
            market_cap=_get_float("market_cap"),
            pe_ratio=_get_float("pe_ratio"),
            forward_pe=_get_float("forward_pe"),
            dividend_yield_pct=_get_float("dividend_yield_pct"),
            fifty_two_week_high=_get_float("fifty_two_week_high"),
            fifty_two_week_low=_get_float("fifty_two_week_low"),
            fifty_two_week_change_pct=_get_float("fifty_two_week_change_pct"),
            fifty_day_average=_get_float("fifty_day_average"),
            two_hundred_day_average=_get_float("two_hundred_day_average"),
            average_volume=_get_int("average_volume"),
            sector=_get_str("sector"),
            industry=_get_str("industry"),
            country=_get_str("country"),
            price_to_book=_get_float("price_to_book"),
            peg_ratio=_get_float("peg_ratio"),
            beta=_get_float("beta"),
            profit_margins_pct=_get_float("profit_margins_pct"),
            gross_margins_pct=_get_float("gross_margins_pct"),
            operating_margins_pct=_get_float("operating_margins_pct"),
            revenue_growth_pct=_get_float("revenue_growth_pct"),
            earnings_growth_pct=_get_float("earnings_growth_pct"),
            return_on_equity_pct=_get_float("return_on_equity_pct"),
            return_on_assets_pct=_get_float("return_on_assets_pct"),
            total_debt_to_equity=_get_float("total_debt_to_equity"),
            free_cashflow=_get_float("free_cashflow"),
            short_ratio=_get_float("short_ratio"),
            target_mean_price=_get_float("target_mean_price"),
            target_high_price=_get_float("target_high_price"),
            target_low_price=_get_float("target_low_price"),
            number_of_analyst_opinions=_get_int("number_of_analyst_opinions"),
            recommendation_key=_get_str("recommendation_key"),
            eps_trailing_ttm=_get_float("eps_trailing_ttm"),
            eps_forward=_get_float("eps_forward"),
            currency=_get_str("currency"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecommendationAction(StrEnum):
    """Supported investment opportunity_evaluation actions."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class UrgencyLevel(StrEnum):
    """Urgency priority levels for recommendation execution."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RebalanceRecommendation(BaseModel):
    """Structured AI recommendation schema for asset portfolio rebalancing."""

    action: RecommendationAction
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=250)
    target_allocation_pct: float = Field(ge=0.0, le=100.0)
    urgency_level: UrgencyLevel
    risk_score: int = Field(ge=1, le=5)
    valuation_score: int = Field(ge=1, le=10)
    expected_dividend_yield_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    ter_impact_assessment: str | None = Field(default=None, max_length=100)


@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    """Represents a single timestamped value point in a time series."""

    date: str
    value: float


@dataclass(frozen=True, slots=True)
class AssetTimeSeries:
    """Stores historical time series metrics for an individual asset."""

    ticker: str
    name: str
    asset_type: str
    value_history: list[TimeSeriesPoint] = field(default_factory=list)
    quantity_history: list[TimeSeriesPoint] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AssetClassTimeSeries:
    """Stores historical valuation and composition split for an asset class."""

    asset_type: str
    value_history: list[TimeSeriesPoint] = field(default_factory=list)
    share_history: list[TimeSeriesPoint] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PortfolioTimeSeries:
    """Stores historical metrics for global portfolio valuation."""

    value_history: list[TimeSeriesPoint] = field(default_factory=list)
    ath_history: list[TimeSeriesPoint] = field(default_factory=list)
    drawdown_history: list[TimeSeriesPoint] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AssetPerformanceSummary:
    """Summary snapshot metrics for an individual asset position."""

    ticker: str
    name: str
    asset_type: str
    latest_quantity: float
    latest_value_eur: float
    cost_basis_eur: float
    roi_eur: float
    roi_percent: float
    portfolio_share_percent: float


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    """Aggregated analytics dataset for terminal rendering and chart generation."""

    portfolio_history: PortfolioTimeSeries
    asset_series: list[AssetTimeSeries]
    class_series: list[AssetClassTimeSeries]
    asset_summaries: list[AssetPerformanceSummary]
    top_growth_contributor: str | None = None
    max_drawdown_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class GrowthMilestone:
    """Represents portfolio growth metrics at a specific year milestone."""

    year: int
    total_invested: float
    compound_interest: float
    projected_value: float
    inflation_adjusted_value: float = 0.0

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GrowthProjectionScenario:
    """Projection scenario with annual return rate, contributions, and milestones."""

    name: str
    annual_return_pct: float
    monthly_contribution: float
    progression: list[GrowthMilestone] = field(default_factory=list)
    milestones: dict[int, GrowthMilestone] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "annual_return_pct": self.annual_return_pct,
            "monthly_contribution": self.monthly_contribution,
            "progression": [item.to_dict() for item in self.progression],
            "milestones": {str(yr): ms.to_dict() for yr, ms in self.milestones.items()},
        }


@dataclass(frozen=True, slots=True)
class GrowthProjectionResult:
    """Consolidated result of portfolio compound growth projections."""

    initial_value: float
    monthly_contribution: float
    scenarios: list[GrowthProjectionScenario]
    historical_cagr_pct: float | None = None
    primary_scenario: GrowthProjectionScenario | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_value": self.initial_value,
            "monthly_contribution": self.monthly_contribution,
            "scenarios": [sc.to_dict() for sc in self.scenarios],
            "historical_cagr_pct": self.historical_cagr_pct,
            "primary_scenario": (
                self.primary_scenario.to_dict() if self.primary_scenario else None
            ),
        }
