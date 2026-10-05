"""Graphics generation module using matplotlib and seaborn to render
visual comparison charts for portfolio allocations.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns  # type: ignore[import-untyped]

from src.config import OUTPUT_DIR
from src.utils.logger.logger import logger

PLOTS_DIR: Path = OUTPUT_DIR / "plots"


def generate_allocation_chart(
    symbols: list[str],
    current_allocations: list[float],
    target_allocations: list[float],
    file_name: str = "allocation_comparison.png",
) -> Path | None:
    """Generates a visual comparison bar chart of current vs target allocations

    and saves it to the plots directory.

    Args:
        symbols: List of asset ticker symbols or names.
        current_allocations: List of current allocation percentages.
        target_allocations: List of target allocation percentages.
        file_name: Filename for the output PNG image.

    Returns:
        Path to the generated plot image file, or None if generation fails.
    """
    if (
        not symbols
        or len(symbols) != len(current_allocations)
        or len(symbols) != len(target_allocations)
    ):
        logger.error(
            "Invalid or mismatched data provided for allocation chart generation."
        )
        return None

    try:
        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path: Path = PLOTS_DIR / file_name

        sns.set_theme(style="whitegrid")
        plt.figure(figsize=(10, 6))

        data: pd.DataFrame = pd.DataFrame(
            {
                "Symbol": symbols * 2,
                "Allocation (%)": current_allocations + target_allocations,
                "Type": ["Current"] * len(symbols) + ["Target"] * len(symbols),
            }
        )

        sns.barplot(
            x="Symbol",
            y="Allocation (%)",
            hue="Type",
            data=data,
            palette="muted",
        )

        plt.title(
            "Portfolio Allocation: Current vs Target",
            fontsize=14,
            fontweight="bold",
        )
        plt.xlabel("Assets", fontsize=12)
        plt.ylabel("Allocation (%)", fontsize=12)
        plt.xticks(rotation=45, ha="right")
        plt.legend(title="Allocation Type")
        plt.tight_layout()

        plt.savefig(file_path, dpi=300)
        plt.close()

        logger.success(
            f"Allocation comparison chart successfully generated at '{file_path}'."
        )
        return file_path

    except Exception as e:
        logger.error(f"Failed to generate allocation chart: {e}")
        return None


# Dark palette validated against report card surface #161b22
_DONUT_COLORS = [
    "#3987e5",  # blue
    "#008300",  # green
    "#d55181",  # magenta
    "#c98500",  # yellow
    "#199e70",  # aqua
    "#d95926",  # orange
    "#9085e9",  # violet
    "#e66767",  # red
]

# Matches report.html.j2 dark theme tokens exactly
_SURFACE = "#161b22"  # .chart-card background
_SURFACE_LABEL = "#0d1117"  # page background used for label contrast
_TEXT_PRIMARY = "#e6edf3"  # h2/h3 colour
_TEXT_SECONDARY = "#8b949e"  # muted/meta colour


def generate_exposure_pie_chart(
    data: dict[str, float], title: str, file_name: str
) -> Path | None:
    """Generates a dark-theme donut chart for exposure data."""
    try:
        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path: Path = PLOTS_DIR / file_name

        sorted_data = dict(sorted(data.items(), key=lambda x: x[1], reverse=True))
        labels = list(sorted_data.keys())
        sizes = list(sorted_data.values())

        n = len(labels)
        colors = [_DONUT_COLORS[i % len(_DONUT_COLORS)] for i in range(n)]

        fig, ax = plt.subplots(figsize=(9, 7), facecolor=_SURFACE)
        ax.set_facecolor(_SURFACE)

        wedges, _ = ax.pie(
            sizes,
            labels=None,
            startangle=90,
            colors=colors,
            wedgeprops={"width": 0.52, "edgecolor": _SURFACE, "linewidth": 2},
            counterclock=False,
        )

        # Direct labels on slices >= 3%
        for wedge, _label, size in zip(wedges, labels, sizes, strict=True):
            if size < 3.0:
                continue
            angle = (wedge.theta1 + wedge.theta2) / 2
            rad = math.radians(angle)
            r = 0.72
            x, y = r * math.cos(rad), r * math.sin(rad)
            ax.text(
                x,
                y,
                f"{size:.1f}%",
                ha="center",
                va="center",
                fontsize=8,
                fontweight="bold",
                color=_SURFACE_LABEL,
            )

        ax.set_title(title, fontsize=13, fontweight="bold", color=_TEXT_PRIMARY, pad=16)

        # Legend — sorted by size, max 8 entries
        legend_labels = [
            f"{lbl}  {sz:.1f}%" for lbl, sz in zip(labels, sizes, strict=True)
        ]
        ax.legend(
            wedges[:8],
            legend_labels[:8],
            loc="lower center",
            bbox_to_anchor=(0.5, -0.18),
            ncol=2,
            frameon=False,
            fontsize=8,
            labelcolor=_TEXT_SECONDARY,
        )

        plt.tight_layout()
        plt.savefig(file_path, dpi=300, bbox_inches="tight", facecolor=_SURFACE)
        plt.close()

        logger.success(f"Exposure chart '{title}' generated at '{file_path}'.")
        return file_path

    except Exception as e:
        logger.error(f"Failed to generate exposure pie chart: {e}")
        return None
