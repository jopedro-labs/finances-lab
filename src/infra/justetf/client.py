"""Infrastructure client for scraping ETF details from JustETF."""

from __future__ import annotations

import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.core.exceptions import JustETFScrapeError
from src.core.models import (
    CountryExposure,
    ETFDetails,
    Holding,
    SectorExposure,
)


class JustETFClient:
    """Scraper client for retrieving ETF holdings and exposure details."""

    BASE_URL: str = "https://www.justetf.com/en/etf-profile.html"
    DEFAULT_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, timeout: float = 10.0, max_retries: int = 3) -> None:
        self.timeout: float = timeout
        self.session: requests.Session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)

        retries: Retry = Retry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter: HTTPAdapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_etf_details(self, isin: str) -> ETFDetails:
        url: str = f"{self.BASE_URL}?isin={isin}"
        try:
            response: requests.Response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                time.sleep(retry_after)
                response = self.session.get(url, timeout=self.timeout)
            if response.status_code != 200:
                raise JustETFScrapeError(
                    f"HTTP error {response.status_code} while fetching ISIN {isin}"
                )
        except requests.RequestException as e:
            raise JustETFScrapeError(
                f"Network error fetching JustETF page for {isin}: {e}"
            ) from e

        try:
            soup: BeautifulSoup = BeautifulSoup(response.text, "html.parser")
            holdings: list[Holding] = self._parse_holdings(soup)
            sectors: list[SectorExposure] = self._parse_sectors(soup)
            countries: list[CountryExposure] = self._parse_countries(soup)
            ter_pct: float | None = self._parse_ter(soup)

            return ETFDetails(
                holdings=holdings,
                sector_breakdown=sectors,
                country_breakdown=countries,
                ter_pct=ter_pct,
            )
        except Exception as e:
            if isinstance(e, JustETFScrapeError):
                raise
            raise JustETFScrapeError(
                f"Failed to parse JustETF response for ISIN {isin}: {e}"
            ) from e

    def _extract_isin_from_element(self, element: Tag) -> str:
        if not element:
            return ""

        anchors: list[Tag] = [element] if element.name == "a" else []
        anchors.extend(element.find_all("a"))

        for link in anchors:
            href: str = str(link.get("href", ""))
            match: re.Match[str] | None = re.search(
                r"([A-Z]{2}[A-Z0-9]{9}\d)", href.upper()
            )
            if match:
                return match.group(1)

        match_raw: re.Match[str] | None = re.search(
            r"([A-Z]{2}[A-Z0-9]{9}\d)", str(element).upper()
        )
        if match_raw:
            return match_raw.group(1)

        return ""

    def _parse_holdings(self, soup: BeautifulSoup) -> list[Holding]:
        holdings: list[Holding] = []
        rows: list[Tag] = soup.find_all(
            "tr", {"data-testid": lambda x: x and "top-holdings_row" in str(x)}
        )

        if not rows:
            container_res: Any = soup.find("table", {"id": "top-holdings"})
            container: Tag | None = (
                container_res if isinstance(container_res, Tag) else None
            )
            if isinstance(container, Tag):
                rows = container.find_all("tr")

        if not rows:
            for table in soup.find_all("table"):
                header_text: str = table.get_text().lower()
                if (
                    ("top holdings" in header_text or "holding" in header_text)
                    and "sector" not in header_text
                    and "country" not in header_text
                ):
                    rows = table.find_all("tr")
                    break

        for row in rows:
            cols: list[Tag] = row.find_all(["td", "th"])
            if len(cols) >= 2:
                name: str = cols[0].get_text(strip=True)
                weight_text: str = cols[-1].get_text(strip=True)
                isin: str = self._extract_isin_from_element(row)

                if not name or name.lower() in [
                    "name",
                    "holding",
                    "weight",
                    "components",
                ]:
                    continue

                match: re.Match[str] | None = re.search(
                    r"(\d+[.,]?\d*)\s*%", weight_text
                )
                if match:
                    try:
                        weight_pct: float = float(match.group(1).replace(",", "."))
                        holdings.append(
                            Holding(
                                name=name,
                                isin=isin,
                                ticker=None,
                                weight_pct=weight_pct,
                            )
                        )
                    except ValueError:
                        continue

        return holdings

    def _parse_sectors(self, soup: BeautifulSoup) -> list[SectorExposure]:
        sectors: list[SectorExposure] = []
        rows: list[Tag] = soup.find_all(
            "tr",
            {
                "data-testid": lambda x: x
                and "sector" in str(x).lower()
                and "row" in str(x).lower()
            },
        )
        if not rows:
            container_res: Any = soup.find("div", {"id": "sectors"})
            container: Tag | None = (
                container_res if isinstance(container_res, Tag) else None
            )
            if isinstance(container, Tag):
                rows = container.find_all("tr")

        if not rows:
            for table in soup.find_all("table"):
                header_text: str = table.get_text().lower()
                if "sector" in header_text and "country" not in header_text:
                    rows = table.find_all("tr")
                    break

        for row in rows:
            cols: list[Tag] = row.find_all(["td", "th"])
            if len(cols) >= 2:
                sector_name: str = cols[0].get_text(strip=True)
                if not sector_name or sector_name.lower() in [
                    "sector",
                    "name",
                    "breakdown",
                    "sector breakdown",
                ]:
                    continue

                weight_text: str = cols[-1].get_text(strip=True)
                match: re.Match[str] | None = re.search(
                    r"(\d+[.,]?\d*)\s*%", weight_text
                )
                if match:
                    try:
                        weight_pct: float = float(match.group(1).replace(",", "."))
                        sectors.append(
                            SectorExposure(
                                sector_name=sector_name,
                                weight_pct=weight_pct,
                            )
                        )
                    except ValueError:
                        continue

        return sectors

    def _parse_countries(self, soup: BeautifulSoup) -> list[CountryExposure]:
        countries: list[CountryExposure] = []
        rows: list[Tag] = soup.find_all(
            "tr",
            {
                "data-testid": lambda x: x
                and "countr" in str(x).lower()
                and "row" in str(x).lower()
            },
        )
        if not rows:
            container_res: Any = soup.find("div", {"id": "countries"})
            container: Tag | None = (
                container_res if isinstance(container_res, Tag) else None
            )
            if isinstance(container, Tag):
                rows = container.find_all("tr")

        if not rows:
            for table in soup.find_all("table"):
                header_text: str = table.get_text().lower()
                if (
                    "country" in header_text
                    or "countries" in header_text
                    or "region" in header_text
                ) and "sector" not in header_text:
                    rows = table.find_all("tr")
                    break

        for row in rows:
            cols: list[Tag] = row.find_all(["td", "th"])
            if len(cols) >= 2:
                country_name: str = cols[0].get_text(strip=True)
                if not country_name or country_name.lower() in [
                    "country",
                    "countries",
                    "region",
                    "name",
                    "region breakdown",
                    "country breakdown",
                ]:
                    continue

                weight_text: str = cols[-1].get_text(strip=True)
                match: re.Match[str] | None = re.search(
                    r"(\d+[.,]?\d*)\s*%", weight_text
                )
                if match:
                    try:
                        weight_pct: float = float(match.group(1).replace(",", "."))
                        countries.append(
                            CountryExposure(
                                country_name=country_name,
                                weight_pct=weight_pct,
                            )
                        )
                    except ValueError:
                        continue

        return countries

    def _parse_ter(self, soup: BeautifulSoup) -> float | None:
        for label in soup.find_all(
            string=re.compile(r"TER|Total\s*Expense\s*Ratio", re.IGNORECASE)
        ):
            parent: Tag | None = label.parent
            if parent:
                search_scope: Tag = parent.parent if parent.parent else parent
                text_content: str = search_scope.get_text()
                match: re.Match[str] | None = re.search(
                    r"(?:TER|Total\s*Expense\s*Ratio)[^%]*?(\d+[.,]?\d*)\s*%",
                    text_content,
                    re.IGNORECASE,
                )
                if match:
                    try:
                        return float(match.group(1).replace(",", "."))
                    except ValueError:
                        pass
        return None
