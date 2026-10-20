"""Module for calculating consolidated geographic, sector,
and company exposure across portfolio assets."""

from __future__ import annotations

from pathlib import Path

from src.config import settings
from src.core.models import Asset, ETFDetails, PortfolioSnapshot, StockDetails
from src.core.providers import ETFProvider, StockProvider
from src.core.repositories import PortfolioRepository, SqlitePortfolioRepository
from src.infra.database.connection import DEFAULT_DB_PATH


class ExposureEngine:
    """Engine responsible for aggregating and calculating portfolio
    exposure by country, sector, and individual company."""

    def __init__(
        self,
        etf_provider: ETFProvider | None = None,
        stock_provider: StockProvider | None = None,
        portfolio_repo: PortfolioRepository | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._etf_provider: ETFProvider = etf_provider or ETFProvider()
        self._stock_provider: StockProvider = stock_provider or StockProvider()
        self._portfolio_repo: PortfolioRepository = (
            portfolio_repo or SqlitePortfolioRepository(DEFAULT_DB_PATH)
        )
        self._db_path: Path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)

    def calculate_consolidated_exposure(
        self, snapshot: PortfolioSnapshot
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Calculates consolidated sector and country exposure
        percentages relative to total portfolio value,
        ensuring full 100% allocation by capturing unmapped
        breakdown remainders into 'Unknown'.
        """
        sector_totals: dict[str, float] = {}
        country_totals: dict[str, float] = {}
        total_portfolio_value: float = snapshot.total_value_eur

        if total_portfolio_value <= 0.0:
            return sector_totals, country_totals

        try:
            assets: list[Asset] = self._portfolio_repo.load_assets()
        except Exception:
            assets = []

        asset_map: dict[str, Asset] = {a.isin: a for a in assets if a.isin}
        snapshot_map: dict[str, float] = {
            s.isin: s.value_eur for s in snapshot.assets_snapshot if s.isin
        }

        for isin, asset in asset_map.items():
            asset_val: float = snapshot_map.get(isin, 0.0)
            if asset_val <= 0.0:
                continue

            a_type: str = str(asset.asset_type).upper()

            if a_type == "ETF" and asset.isin:
                details: ETFDetails | None = self._etf_provider.get_details(
                    asset, db_path=self._db_path
                )
                if details:
                    mapped_sector_val: float = 0.0
                    if details.sector_breakdown:
                        for sector in details.sector_breakdown:
                            sec_name: str = sector.sector_name
                            sec_weight: float = sector.weight_pct / 100.0
                            sec_weighted_val: float = asset_val * sec_weight
                            sector_totals[sec_name] = (
                                sector_totals.get(sec_name, 0.0) + sec_weighted_val
                            )
                            mapped_sector_val += sec_weighted_val

                    unmapped_sector_val: float = asset_val - mapped_sector_val
                    if unmapped_sector_val > 0.0:
                        sector_totals["Unknown"] = (
                            sector_totals.get("Unknown", 0.0) + unmapped_sector_val
                        )

                    mapped_country_val: float = 0.0
                    if details.country_breakdown:
                        for country in details.country_breakdown:
                            cou_name: str = country.country_name
                            cou_weight: float = country.weight_pct / 100.0
                            cou_weighted_val: float = asset_val * cou_weight
                            country_totals[cou_name] = (
                                country_totals.get(cou_name, 0.0) + cou_weighted_val
                            )
                            mapped_country_val += cou_weighted_val

                    unmapped_country_val: float = asset_val - mapped_country_val
                    if unmapped_country_val > 0.0:
                        country_totals["Unknown"] = (
                            country_totals.get("Unknown", 0.0) + unmapped_country_val
                        )
                else:
                    sector_totals["Unknown"] = (
                        sector_totals.get("Unknown", 0.0) + asset_val
                    )
                    country_totals["Unknown"] = (
                        country_totals.get("Unknown", 0.0) + asset_val
                    )
            elif a_type == "STOCK":
                stock_details: StockDetails | None = self._stock_provider.get_details(
                    asset, db_path=self._db_path
                )
                stock_sector_name: str = (
                    stock_details.sector
                    if stock_details and stock_details.sector
                    else "Unknown"
                )
                sector_totals[stock_sector_name] = (
                    sector_totals.get(stock_sector_name, 0.0) + asset_val
                )
                stock_country_name: str = (
                    stock_details.country
                    if stock_details and stock_details.country
                    else "Unknown"
                )
                country_totals[stock_country_name] = (
                    country_totals.get(stock_country_name, 0.0) + asset_val
                )

        sector_percentages: dict[str, float] = {
            sec: round((val / total_portfolio_value) * 100.0, 2)
            for sec, val in sorted(
                sector_totals.items(), key=lambda item: item[1], reverse=True
            )
        }
        country_percentages: dict[str, float] = {
            cou: round((val / total_portfolio_value) * 100.0, 2)
            for cou, val in sorted(
                country_totals.items(), key=lambda item: item[1], reverse=True
            )
        }

        return sector_percentages, country_percentages

    def calculate_penalty_factor(
        self,
        sector: str | None = None,
        country: str | None = None,
        sector_percentages: dict[str, float] | None = None,
        country_percentages: dict[str, float] | None = None,
    ) -> float:
        """Calculates multiplicative penalty factor based on sector and country
        exposure limit breaches.

        Args:
            sector: Asset sector name.
            country: Asset country or region name.
            sector_percentages: Pre-calculated portfolio sector exposure percentages.
            country_percentages: Pre-calculated portfolio country exposure percentages.

        Returns:
            Multiplicative penalty factor between 0.0 and 1.0.
        """
        sector_factor: float = 1.0
        country_factor: float = 1.0

        if sector and sector.lower() != "unknown" and sector_percentages:
            sec_exposure: float = sector_percentages.get(sector, 0.0)
            is_tech_sector: bool = (
                "technology" in sector.lower() or "tech" in sector.lower()
            )
            sec_limit: float = (
                settings.max_tech_allocation_pct
                if is_tech_sector
                else settings.max_other_sector_allocation_pct
            )
            if sec_exposure > sec_limit and sec_limit > 0.0:
                sec_excess_ratio: float = min(
                    1.0, (sec_exposure - sec_limit) / sec_limit
                )
                sector_factor -= (
                    settings.exposure_sector_penalty_weight * sec_excess_ratio
                )

        if country and country.lower() != "unknown" and country_percentages:
            cou_exposure: float = country_percentages.get(country, 0.0)
            cou_limit: float = settings.max_country_allocation_pct
            if cou_exposure > cou_limit and cou_limit > 0.0:
                cou_excess_ratio: float = min(
                    1.0, (cou_exposure - cou_limit) / cou_limit
                )
                country_factor -= (
                    settings.exposure_country_penalty_weight * cou_excess_ratio
                )

        return max(0.0, sector_factor * country_factor)

    def validate_exposure_limits(
        self,
        sector_percentages: dict[str, float],
        country_percentages: dict[str, float],
    ) -> list[str]:
        """Validates current exposures against defined policy caps,
        ignoring unmapped 'Unknown' categories."""
        violations: list[str] = []

        # Validate country limits (max 60%)
        for country, pct in country_percentages.items():
            if country.lower() == "unknown":
                continue
            max_country_limit: float = settings.max_country_allocation_pct
            if pct > max_country_limit:
                violations.append(
                    f"Country limit exceeded for '{country}': "
                    f"{pct:.1f}% (Max allowed: {max_country_limit:.1f}%)"
                )

        # Validate sector limits (Tech max 50%, others max configured threshold)
        for sector, pct in sector_percentages.items():
            if sector.lower() == "unknown":
                continue
            is_tech_sector: bool = (
                "technology" in sector.lower() or "tech" in sector.lower()
            )
            limit: float = (
                settings.max_tech_allocation_pct
                if is_tech_sector
                else settings.max_other_sector_allocation_pct
            )
            if pct > limit:
                violations.append(
                    f"Sector limit exceeded for '{sector}': "
                    f"{pct:.1f}% (Max allowed: {limit:.1f}%)"
                )

        return violations

    def calculate_company_exposure(
        self, snapshot: PortfolioSnapshot
    ) -> dict[str, float]:
        """Calculates consolidated individual company exposure across
        direct stocks and ETF holdings grouped strictly by ISIN."""
        company_totals: dict[str, float] = {}
        isin_to_name: dict[str, str] = {}
        total_portfolio_value: float = snapshot.total_value_eur

        if total_portfolio_value <= 0.0:
            return company_totals

        try:
            assets: list[Asset] = self._portfolio_repo.load_assets()
        except Exception:
            assets = []

        asset_map: dict[str, Asset] = {a.isin: a for a in assets if a.isin}
        snapshot_map: dict[str, float] = {
            s.isin: s.value_eur for s in snapshot.assets_snapshot if s.isin
        }

        # 1. Aggregate direct portfolio stocks by ISIN
        for isin, asset in asset_map.items():
            dir_asset_value: float = snapshot_map.get(isin, 0.0)
            if dir_asset_value <= 0.0:
                continue

            dir_asset_type: str = str(asset.asset_type).upper()
            isin_to_name[isin] = asset.name

            if dir_asset_type == "STOCK":
                company_totals[isin] = company_totals.get(isin, 0.0) + dir_asset_value

        # 2. Aggregate underlying ETF holdings via look-through by ISIN
        for isin, asset in asset_map.items():
            etf_asset_value: float = snapshot_map.get(isin, 0.0)
            if etf_asset_value <= 0.0:
                continue

            etf_asset_type: str = str(asset.asset_type).upper()
            if etf_asset_type == "ETF":
                details: ETFDetails | None = self._etf_provider.get_details(
                    asset, db_path=self._db_path
                )
                if details and details.holdings:
                    for holding in details.holdings:
                        holding_isin: str = (
                            holding.isin if holding.isin else holding.name
                        )
                        h_weight: float = holding.weight_pct / 100.0
                        h_weighted_val: float = etf_asset_value * h_weight

                        company_totals[holding_isin] = (
                            company_totals.get(holding_isin, 0.0) + h_weighted_val
                        )
                        if holding_isin not in isin_to_name:
                            isin_to_name[holding_isin] = holding.name

        # Consolidate values by display name before calculating percentages
        display_totals: dict[str, float] = {}
        for isin_key, val in company_totals.items():
            disp_name: str = isin_to_name.get(isin_key, isin_key)
            display_totals[disp_name] = display_totals.get(disp_name, 0.0) + val

        company_percentages: dict[str, float] = {
            disp_name: round((val / total_portfolio_value) * 100.0, 2)
            for disp_name, val in sorted(
                display_totals.items(), key=lambda item: item[1], reverse=True
            )
        }

        return company_percentages

    def validate_company_limits(
        self, company_percentages: dict[str, float]
    ) -> list[str]:
        """Validates individual company exposure against the configured policy cap."""
        violations: list[str] = []
        max_limit: float = settings.max_company_allocation_pct

        for company, pct in company_percentages.items():
            if pct > max_limit:
                violations.append(
                    f"Company limit exceeded for '{company}': "
                    f"{pct:.1f}% (Max allowed: {max_limit:.1f}%)"
                )

        return violations
