"""Automated executive portfolio report generator (HTML + PDF)."""

from __future__ import annotations

import base64
import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2
from markupsafe import Markup

from src.config import DATA_DIR, settings
from src.core.models import (
    Asset,
    AssetPerformanceSummary,
    DashboardOverview,
    GrowthProjectionScenario,
)
from src.core.portfolio_analytics import PortfolioAnalyticsEngine
from src.core.projections import ProjectionEngine
from src.core.repositories import SqlitePortfolioRepository
from src.infra.database.connection import DEFAULT_DB_PATH
from src.infra.database.finance_sql_extraction import (
    AssetHistoricalRecord,
    FinanceSQLExtractor,
    PortfolioHistoricalRecord,
)
from src.utils.graphics.portfolio_charts import PortfolioChartExporter

_DEFAULT_TEMPLATE_DIR: Path = Path(__file__).resolve().parent.parent / "templates"


class PortfolioReportGenerator:
    """Generates a dark-theme HTML + PDF executive portfolio report."""

    def __init__(
        self,
        db_path: Path = Path(DEFAULT_DB_PATH),
        config_path: Path = DATA_DIR / "portfolio.json",
        output_dir: Path = Path("output/reports"),
        template_dir: Path = _DEFAULT_TEMPLATE_DIR,
        monthly_contribution: float = 500.0,
    ) -> None:
        self.db_path = db_path
        self.config_path = config_path
        self.output_dir = output_dir
        self.monthly_contribution = monthly_contribution
        self._jinja_env: jinja2.Environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=jinja2.select_autoescape(["html"]),
        )

    def _build_overview(self) -> DashboardOverview:
        extractor = FinanceSQLExtractor(db_path=self.db_path)
        asset_records: list[AssetHistoricalRecord] = extractor.fetch_asset_history()
        portfolio_records: list[PortfolioHistoricalRecord] = (
            extractor.fetch_portfolio_history()
        )

        current_assets: list[Asset] = []
        try:
            current_assets = SqlitePortfolioRepository(self.db_path).load_assets()
        except Exception:  # nosec B110
            pass

        if not current_assets and self.config_path.exists():
            try:
                data: Any = json.loads(self.config_path.read_text(encoding="utf-8"))
                items: list[dict[str, Any]] = (
                    data if isinstance(data, list) else data.get("assets", [])
                )
                current_assets = [Asset.from_dict(item) for item in items]
            except Exception:  # nosec B110
                pass

        return PortfolioAnalyticsEngine().build_dashboard_overview(
            asset_records=asset_records,
            portfolio_records=portfolio_records,
            current_assets=current_assets,
        )

    @staticmethod
    def _chart_to_b64(chart_path: Path) -> Markup:
        """Returns a Markup-wrapped base64 string for safe embedding in HTML."""
        if not chart_path.exists():
            return Markup("")
        return Markup(
            base64.b64encode(chart_path.read_bytes()).decode("utf-8")
        )  # nosec B704

    def _build_growth_scenarios(self) -> list[dict[str, Any]]:
        extractor = FinanceSQLExtractor(db_path=self.db_path)
        history = extractor.fetch_portfolio_history()
        initial_value: float = history[-1].total_value_eur if history else 0.0

        engine = ProjectionEngine()
        scenarios_def = [
            ("Conservative", 0.05),
            ("Moderate", 0.07),
            ("Aggressive", 0.09),
        ]
        result: list[dict[str, Any]] = []
        for name, rate in scenarios_def:
            scenario: GrowthProjectionScenario = engine.generate_scenario(
                name, initial_value, self.monthly_contribution, rate
            )
            milestones = [
                {
                    "year": yr,
                    "projected_value": scenario.milestones[yr].projected_value,
                    "inflation_adjusted_value": scenario.milestones[
                        yr
                    ].inflation_adjusted_value,
                    "compound_interest": scenario.milestones[yr].compound_interest,
                    "total_invested": scenario.milestones[yr].total_invested,
                }
                for yr in [10, 20, 30]
                if yr in scenario.milestones
            ]
            result.append(
                {
                    "name": name,
                    "annual_return_pct": rate * 100,
                    "milestones": milestones,
                }
            )
        return result

    def _build_template_context(
        self,
        overview: DashboardOverview,
        chart_valuation_b64: Markup,
        chart_class_b64: Markup,
        generated_at: str,
    ) -> dict[str, Any]:
        value_history = overview.portfolio_history.value_history

        def _fmt_period(raw: str) -> str:
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            return raw

        period_start: str = _fmt_period(value_history[0].date) if value_history else "—"
        period_end: str = _fmt_period(value_history[-1].date) if value_history else "—"
        total_value_eur: float = value_history[-1].value if value_history else 0.0
        summaries: list[AssetPerformanceSummary] = overview.asset_summaries
        total_cost_basis_eur: float = sum(s.cost_basis_eur for s in summaries)
        total_roi_eur: float = sum(s.roi_eur for s in summaries)
        total_roi_percent: float = (
            (total_roi_eur / total_cost_basis_eur * 100.0)
            if total_cost_basis_eur > 0
            else 0.0
        )

        asset_dicts: list[dict[str, Any]] = [
            {
                "ticker": s.ticker,
                "name": s.name,
                "asset_type": s.asset_type,
                "latest_quantity": s.latest_quantity,
                "latest_value_eur": s.latest_value_eur,
                "cost_basis_eur": s.cost_basis_eur,
                "roi_eur": s.roi_eur,
                "roi_percent": s.roi_percent,
                "portfolio_share_percent": s.portfolio_share_percent,
            }
            for s in summaries
        ]

        class_totals: dict[str, float] = {}
        for s in summaries:
            key = s.asset_type.upper()
            class_totals[key] = class_totals.get(key, 0.0) + s.latest_value_eur
        composition: list[dict[str, Any]] = [
            {
                "asset_type": k,
                "value_eur": v,
                "share_percent": (
                    (v / total_value_eur * 100.0) if total_value_eur > 0 else 0.0
                ),
            }
            for k, v in sorted(class_totals.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "generated_at": generated_at,
            "period_start": period_start,
            "period_end": period_end,
            "total_value_eur": total_value_eur,
            "total_cost_basis_eur": total_cost_basis_eur,
            "total_roi_eur": total_roi_eur,
            "total_roi_percent": total_roi_percent,
            "max_drawdown_percent": overview.max_drawdown_percent,
            "top_growth_contributor": overview.top_growth_contributor,
            "asset_summaries": asset_dicts,
            "composition": composition,
            "chart_valuation_b64": chart_valuation_b64,
            "chart_class_b64": chart_class_b64,
            "exposure_plots": self._load_exposure_plots(),
            "growth_scenarios": self._build_growth_scenarios(),
        }

    def _load_exposure_plots(self) -> dict[str, str]:
        """Loads exposure chart images as base64 strings."""
        plots_dir = Path("output/plots")
        plots = {}
        for name in [
            "exposure_sector.png",
            "exposure_country.png",
            "exposure_company.png",
        ]:
            path = plots_dir / name
            if path.exists():
                with open(path, "rb") as f:
                    plots[name.split(".")[0]] = base64.b64encode(f.read()).decode(
                        "utf-8"
                    )
        return plots

    def _build_quality_context(self) -> dict[str, Any]:
        """Builds the full quality tab context from the latest DB snapshots."""
        import json as _json
        from collections import Counter

        from src.infra.database.connection import get_db_context
        from src.infra.database.schema import initialize_database

        assets: list[dict[str, Any]] = []
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT a.name, a.yahoo_ticker as symbol, a.isin,
                           sfh.pe_ratio, sfh.forward_pe, sfh.dividend_yield_pct,
                           sfh.fifty_two_week_high, sfh.fifty_two_week_low,
                           sfh.quality_tier, sfh.quality_score
                    FROM stock_fundamental_history sfh
                    JOIN assets a ON sfh.asset_id = a.id
                    WHERE sfh.id IN (
                        SELECT MAX(id) FROM stock_fundamental_history GROUP BY asset_id
                    )
                    ORDER BY a.id ASC
                """)
                for row in cursor.fetchall():
                    r = dict(row)
                    pe = r.get("pe_ratio")
                    fwd_pe = r.get("forward_pe")
                    div = r.get("dividend_yield_pct")
                    high = r.get("fifty_two_week_high")
                    low = r.get("fifty_two_week_low")
                    tier = r.get("quality_tier") or "Tier C"
                    score = r.get("quality_score") or 0

                    valuation_status = "Fair Value"
                    if pe is not None:
                        valuation_status = (
                            "Undervalued"
                            if pe < 15.0
                            else ("Overvalued" if pe > 30.0 else "Fair Value")
                        )

                    bull: list[str] = []
                    bear: list[str] = []
                    if fwd_pe is not None and fwd_pe < 20.0:
                        bull.append(
                            f"Attractive forward valuation (Fwd P/E: {fwd_pe:.1f})"
                        )
                    if div is not None and div > 0:
                        bull.append(f"Dividend income ({div:.2f}%)")
                    if not bull:
                        bull.append(
                            "Established business model with stable market presence"
                        )
                    if pe is not None and pe > 30.0:
                        bear.append(
                            f"Elevated trailing P/E ({pe:.1f}) may limit upside"
                        )
                    if not bear:
                        bear.append(
                            "No critical balance sheet vulnerabilities detected"
                        )

                    assets.append(
                        {
                            "name": r["name"],
                            "symbol": r["symbol"],
                            "asset_type": "STOCK",
                            "tier": tier,
                            "score": score,
                            "valuation_status": valuation_status,
                            "bull_case": bull,
                            "bear_case": bear,
                            "tr_str": f"{pe:.1f}" if pe else "N/A",
                            "fw_str": f"{fwd_pe:.1f}" if fwd_pe else "N/A",
                            "peg_str": "N/A",
                            "pb_str": "N/A",
                            "div_str": f"{div:.2f}%" if div else "N/A",
                            "beta_str": "N/A",
                            "margin_str": "N/A",
                            "rev_str": "N/A",
                            "earn_str": "N/A",
                            "debt_str": "N/A",
                            "low_str": f"{low:,.2f} EUR" if low else "N/A",
                            "peak_str": f"{high:,.2f} EUR" if high else "N/A",
                        }
                    )

                cursor.execute("""
                    SELECT a.name, a.yahoo_ticker as symbol, a.isin,
                           efh.ter_pct, efh.holdings_json,
                           efh.sector_breakdown_json, efh.country_breakdown_json,
                           efh.quality_tier, efh.quality_score
                    FROM etf_fundamental_history efh
                    JOIN assets a ON efh.asset_id = a.id
                    WHERE efh.id IN (
                        SELECT MAX(id) FROM etf_fundamental_history GROUP BY asset_id
                    )
                    ORDER BY a.id ASC
                """)
                for row in cursor.fetchall():
                    r = dict(row)
                    ter = r.get("ter_pct")
                    tier = r.get("quality_tier") or "Tier C"
                    score = r.get("quality_score") or 0

                    holdings: list[Any] = (
                        _json.loads(r["holdings_json"])
                        if r.get("holdings_json")
                        else []
                    )
                    sectors: list[Any] = (
                        _json.loads(r["sector_breakdown_json"])
                        if r.get("sector_breakdown_json")
                        else []
                    )
                    countries: list[Any] = (
                        _json.loads(r["country_breakdown_json"])
                        if r.get("country_breakdown_json")
                        else []
                    )

                    ter_str = f"{ter:.2f}%" if ter is not None else "N/A"
                    holdings_str = (
                        ", ".join(
                            f"{h.get('name','')} ({float(h.get('weight_pct',0)):.1f}%)"
                            for h in holdings[:5]
                        )
                        or "N/A"
                    )
                    sectors_str = (
                        ", ".join(
                            f"{s.get('sector_name') or s.get('name', '')}"
                            f" ({float(s.get('weight_pct', 0)):.1f}%)"
                            for s in sectors[:4]
                        )
                        or "N/A"
                    )
                    countries_str = (
                        ", ".join(
                            f"{c.get('country_name') or c.get('name', '')}"
                            f" ({float(c.get('weight_pct', 0)):.1f}%)"
                            for c in countries[:4]
                        )
                        or "N/A"
                    )

                    assets.append(
                        {
                            "name": r["name"],
                            "symbol": r["symbol"],
                            "asset_type": "ETF",
                            "tier": tier,
                            "score": score,
                            "valuation_status": "Fair Value",
                            "bull_case": [
                                f"Attractive cost efficiency (TER: {ter_str})",
                                "Fund scale and liquidity",
                            ],
                            "bear_case": [
                                "Market systemic exposure without"
                                " individual stock selection",
                                "Regulatory or structural tracking risks",
                            ],
                            "ter_str": ter_str,
                            "holdings_str": holdings_str,
                            "sectors_str": sectors_str,
                            "countries_str": countries_str,
                        }
                    )
        except Exception:
            return {"assets": [], "kpis": {}}

        tiers = Counter(a["tier"] for a in assets)
        valuations = Counter(a["valuation_status"] for a in assets)
        kpis = {
            "total": len(assets),
            "tier_a": tiers.get("Tier A", 0),
            "tier_b": tiers.get("Tier B", 0),
            "tier_c": tiers.get("Tier C", 0),
            "undervalued": valuations.get("Undervalued", 0),
            "overvalued": valuations.get("Overvalued", 0),
        }
        return {"assets": assets, "kpis": kpis}

    def _build_opportunity_context(self) -> dict[str, Any]:
        """Loads the latest opportunity run from SQLite for the Opportunity tab."""
        from src.infra.database.connection import get_db_context
        from src.infra.database.schema import initialize_database

        empty: dict[str, Any] = {
            "opp_assets": [],
            "opp_advisories": [],
            "opp_has_ai": False,
            "opp_total_value_eur": 0.0,
            "opp_w_stock_dip": settings.stock_weight_dip,
            "opp_w_stock_pe": settings.stock_weight_forward_pe,
            "opp_w_stock_52w": settings.stock_weight_52w_range,
            "opp_w_stock_gap": settings.stock_weight_allocation,
            "opp_w_etf_dip": settings.etf_weight_dip,
            "opp_w_etf_ter": settings.etf_weight_ter,
            "opp_w_etf_gap": settings.etf_weight_allocation,
            "opp_w_sector_pen": settings.exposure_sector_penalty_weight,
            "opp_w_country_pen": settings.exposure_country_penalty_weight,
        }
        if not self.db_path.exists():
            return empty
        try:
            with get_db_context(str(self.db_path)) as conn:
                initialize_database(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, total_value_eur, has_ai FROM opportunities"
                    " ORDER BY id DESC LIMIT 1"
                )
                opp_row = cursor.fetchone()
                if not opp_row:
                    return empty
                opp_id = opp_row["id"]
                total_val = float(opp_row["total_value_eur"])
                has_ai = bool(opp_row["has_ai"])

                cursor.execute(
                    """
                    SELECT symbol, asset_type, rank, price_eur,
                           current_allocation_pct, target_allocation_pct,
                           dip_score, cost_score, gap_score, quant_score,
                           ai_action, ai_urgency, ai_confidence_pct,
                           forward_pe, trailing_pe, peg_ratio, price_to_book,
                           dividend_yield_pct, ter, advisory_json
                    FROM opportunity_asset_metrics
                    WHERE opportunity_id = ?
                    ORDER BY rank ASC
                    """,
                    (opp_id,),
                )
                assets: list[dict[str, Any]] = []
                advisories: list[dict[str, Any]] = []
                for row in cursor.fetchall():
                    r = dict(row)
                    conf = r.get("ai_confidence_pct")
                    assets.append(
                        {
                            "rank": r["rank"],
                            "symbol": r["symbol"],
                            "asset_type": r["asset_type"],
                            "price_eur": float(r["price_eur"]),
                            "current_pct": float(r["current_allocation_pct"]),
                            "target_pct": float(r["target_allocation_pct"]),
                            "score": float(r["quant_score"]),
                            "ai_action": r.get("ai_action"),
                            "ai_urgency": r.get("ai_urgency"),
                            "ai_conf": f"{conf:.0f}%" if conf is not None else None,
                        }
                    )
                    raw_adv = r.get("advisory_json")
                    if raw_adv:
                        try:
                            adv = json.loads(raw_adv)
                            advisories.append(adv)
                        except Exception:  # nosec B110
                            pass

                return {
                    "opp_assets": assets,
                    "opp_advisories": advisories,
                    "opp_has_ai": has_ai,
                    "opp_total_value_eur": total_val,
                    "opp_w_stock_dip": settings.stock_weight_dip,
                    "opp_w_stock_pe": settings.stock_weight_forward_pe,
                    "opp_w_stock_52w": settings.stock_weight_52w_range,
                    "opp_w_stock_gap": settings.stock_weight_allocation,
                    "opp_w_etf_dip": settings.etf_weight_dip,
                    "opp_w_etf_ter": settings.etf_weight_ter,
                    "opp_w_etf_gap": settings.etf_weight_allocation,
                    "opp_w_sector_pen": settings.exposure_sector_penalty_weight,
                    "opp_w_country_pen": settings.exposure_country_penalty_weight,
                }
        except Exception:
            return empty

    def generate(self, open_browser: bool = True) -> Path:
        """Generates the HTML report and returns html_path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html_path = self.output_dir / "portfolio_report.html"

        overview = self._build_overview()

        chart_exporter = PortfolioChartExporter()
        val_path = chart_exporter.export_portfolio_valuation_chart(overview)
        class_path = chart_exporter.export_asset_class_chart(overview)
        chart_valuation_b64 = self._chart_to_b64(val_path)
        chart_class_b64 = self._chart_to_b64(class_path)

        context = self._build_template_context(
            overview=overview,
            chart_valuation_b64=chart_valuation_b64,
            chart_class_b64=chart_class_b64,
            generated_at=generated_at,
        )

        quality_ctx = self._build_quality_context()
        context["quality_assets"] = quality_ctx["assets"]
        context["quality_kpis"] = quality_ctx["kpis"]

        opp_ctx = self._build_opportunity_context()
        context.update(opp_ctx)

        template = self._jinja_env.get_template("report.html.j2")
        html_content = template.render(**context)

        html_path.write_text(html_content, encoding="utf-8")

        if open_browser:
            webbrowser.open(html_path.resolve().as_uri())

        return html_path
