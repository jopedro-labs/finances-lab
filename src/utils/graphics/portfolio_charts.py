"""Module for generating and exporting portfolio performance charts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use(
    "Agg"
)  # Must be set before importing pyplot; safe for non-interactive/server use
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from src.config import OUTPUT_DIR
from src.core.models import DashboardOverview


def _catmull_rom_smooth(
    x: np.ndarray, y: np.ndarray, n_points: int = 400
) -> tuple[np.ndarray, np.ndarray]:
    """Returns smoothed (x, y) arrays using Catmull-Rom spline interpolation."""
    if len(x) < 3:
        return x, y

    xs, ys = [x[0]], [y[0]]
    for i in range(len(x) - 1):
        p0 = x[max(0, i - 1)], y[max(0, i - 1)]
        p1 = x[i], y[i]
        p2 = x[i + 1], y[i + 1]
        p3 = x[min(len(x) - 1, i + 2)], y[min(len(y) - 1, i + 2)]
        n = max(2, n_points // (len(x) - 1))
        for t in np.linspace(0, 1, n, endpoint=(i == len(x) - 2)):
            t2, t3 = t * t, t * t * t
            cx = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            cy = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            xs.append(cx)
            ys.append(cy)

    return np.array(xs), np.array(ys)


def _apply_dark_style(fig: Any, ax: Any) -> None:
    """Applies consistent dark GitHub-style theme to a matplotlib figure."""
    bg = "#0d1117"
    grid_color = "#21262d"
    text_color = "#8b949e"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color, labelsize=9)
    ax.xaxis.label.set_color(text_color)
    ax.yaxis.label.set_color(text_color)
    ax.title.set_color("#e6edf3")
    ax.grid(True, color=grid_color, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)


class PortfolioChartExporter:
    """Exports matplotlib charts for portfolio and asset performance history."""

    def __init__(self, output_dir: Path | str = OUTPUT_DIR / "plots") -> None:
        self.output_dir: Path = Path(output_dir)

    def _ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _parse_dates(self, history_points: list[Any]) -> list[datetime]:
        """Parses snapshot date strings into datetime objects robustly."""
        parsed_dates: list[datetime] = []
        for pt in history_points:
            try:
                clean_date = pt.date.replace(" ", "T")
                d = datetime.fromisoformat(clean_date)
            except Exception:
                try:
                    d = datetime.strptime(pt.date, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    d = datetime.strptime(pt.date, "%Y-%m-%d")
            parsed_dates.append(d)
        return parsed_dates

    def export_portfolio_valuation_chart(self, overview: DashboardOverview) -> Path:
        """Generates and exports the global portfolio valuation chart."""
        self._ensure_output_dir()
        output_path: Path = self.output_dir / "portfolio_valuation.png"

        history = overview.portfolio_history.value_history
        if not history:
            return output_path

        parsed_dates = self._parse_dates(history)
        values: list[float] = [pt.value for pt in history]

        x = np.array(mdates.date2num(parsed_dates))  # type: ignore[no-untyped-call]
        y = np.array(values, dtype=float)
        xs, ys = _catmull_rom_smooth(x, y)

        fig, ax = plt.subplots(figsize=(10, 5))
        _apply_dark_style(fig, ax)

        line_color = "#58a6ff"
        ax.plot(xs, ys, color=line_color, linewidth=2.0)
        ax.fill_between(xs, ys, alpha=0.15, color="#1f6feb")
        ax.scatter(
            x, y, color="white", s=18, zorder=5, linewidths=1.2, edgecolors=line_color
        )

        ax.set_title(
            "Portfolio Valuation History", fontsize=13, fontweight="bold", pad=12
        )
        ax.set_xlabel("Date", fontsize=10)
        ax.set_ylabel("Value (€)", fontsize=10)

        ax.xaxis.set_major_locator(mdates.MonthLocator())  # type: ignore[no-untyped-call]
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))  # type: ignore[no-untyped-call]
        plt.xticks(rotation=45)

        legend = ax.legend(
            ["Portfolio Value (€)"],
            loc="upper left",
            framealpha=0.15,
            edgecolor="#30363d",
            fontsize=9,
        )
        for text in legend.get_texts():
            text.set_color("#c9d1d9")

        plt.tight_layout()
        fig.savefig(output_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        return output_path

    def export_asset_class_chart(self, overview: DashboardOverview) -> Path:
        """Generates and exports comparative asset class valuation trends."""
        self._ensure_output_dir()
        output_path: Path = self.output_dir / "asset_class_evolution.png"

        fig, ax = plt.subplots(figsize=(10, 5))
        _apply_dark_style(fig, ax)

        all_dates_set: set[str] = set()
        for series in overview.class_series:
            for pt in series.value_history:
                all_dates_set.add(pt.date)

        if not all_dates_set:
            plt.close(fig)
            return output_path

        sorted_date_strings = sorted(list(all_dates_set))

        class Pt:
            def __init__(self, d: str):
                self.date = d

        all_series_dates = self._parse_dates([Pt(d) for d in sorted_date_strings])
        x_base = np.array(mdates.date2num(all_series_dates))  # type: ignore[no-untyped-call]

        palette = ["#58a6ff", "#3fb950", "#f78166", "#d2a679", "#a5d6ff"]
        sorted_series = sorted(overview.class_series, key=lambda s: s.asset_type)

        has_data = False
        for idx, class_series in enumerate(sorted_series):
            has_data = True
            data_map = {pt.date: pt.value for pt in class_series.value_history}
            y = np.array(
                [data_map.get(d, 0.0) for d in sorted_date_strings], dtype=float
            )
            color = palette[idx % len(palette)]
            xs, ys = _catmull_rom_smooth(x_base, y)
            ax.plot(xs, ys, label=class_series.asset_type, color=color, linewidth=2.0)
            ax.fill_between(xs, ys, alpha=0.08, color=color)
            ax.scatter(
                x_base,
                y,
                color="white",
                s=14,
                zorder=5,
                linewidths=1.0,
                edgecolors=color,
            )

        if not has_data:
            plt.close(fig)
            return output_path

        ax.set_title(
            "Asset Class Valuation History", fontsize=13, fontweight="bold", pad=12
        )
        ax.set_xlabel("Date", fontsize=10)
        ax.set_ylabel("Value (€)", fontsize=10)

        ax.xaxis.set_major_locator(mdates.MonthLocator())  # type: ignore[no-untyped-call]
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))  # type: ignore[no-untyped-call]
        plt.xticks(rotation=45)

        legend = ax.legend(
            loc="upper left",
            framealpha=0.15,
            edgecolor="#30363d",
            fontsize=9,
        )
        for text in legend.get_texts():
            text.set_color("#c9d1d9")

        plt.tight_layout()
        fig.savefig(output_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        return output_path
