"""Render the frozen README comparison data; never read live experiment files."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

BLUE = "#2E8BCC"
GRAY = "#AAB5BE"
INK = "#1F2D3A"
SOFT = "#4F5E6D"
RULE = "#D3DDE4"


def render_panel(key, section, output):
    """Keep source values intact; only displayed labels are rounded."""
    physics = key == "physics"
    height = 4.0 if physics else 7.1
    fig = plt.figure(figsize=(12.4, height), facecolor="white")
    card = FancyBboxPatch(
        (0.015, 0.025),
        0.97,
        0.95,
        boxstyle="round,pad=0,rounding_size=0.018",
        transform=fig.transFigure,
        facecolor="#FAFBFC",
        edgecolor=RULE,
        linewidth=1,
        zorder=-5,
    )
    fig.add_artist(card)
    fig.text(
        0.04,
        1 - 0.31 / height,
        "Physics time series" if physics else "Cancer gene identification",
        fontsize=19,
        weight="bold",
        va="top",
    )
    subtitle = (
        "Published validation results · S4D reference"
        if physics
        else "Best Formal result · adaptive test feedback · TREE reference"
    )
    fig.text(0.04, 1 - 0.65 / height, subtitle, fontsize=11.5, color=SOFT, va="top")
    fig.legend(
        handles=[
            Patch(color=BLUE, label="SIDERIUS"),
            Patch(color=GRAY, label="Human expert baseline"),
        ],
        loc="upper right",
        bbox_to_anchor=(0.955, 1 - 0.28 / height),
        ncol=2,
        frameon=False,
        fontsize=11,
        handlelength=1.5,
        columnspacing=1.5,
    )
    ax = fig.add_axes([0.175, 0.76 / height, 0.59, 1 - 1.82 / height], facecolor="none")
    minimum, maximum = (0, 1) if physics else (0.5, 0.92)
    rows = section["rows"]
    for i, row in enumerate(rows):
        for field, offset, color in [("siderius", -0.16, BLUE), ("baseline", 0.16, GRAY)]:
            value = row[field]
            ax.barh(i + offset, value - minimum, left=minimum, height=0.27, color=color, zorder=3)
            ax.text(
                1.07,
                i + offset,
                f"{value:.3f}",
                transform=ax.get_yaxis_transform(),
                ha="center",
                va="center",
                fontsize=12 if field == "siderius" else 11,
                color="#2277B8" if field == "siderius" else SOFT,
                weight="bold" if field == "siderius" else "normal",
            )
        delta = row["siderius"] - row["baseline"]
        label = f"{delta:+.3f}" if physics else f"{delta * 100:+.1f}"
        ax.text(
            1.26,
            i,
            label,
            transform=ax.get_yaxis_transform(),
            ha="center",
            va="center",
            weight="bold",
            fontsize=12,
            color="#12866F" if delta >= 0 else "#9B5D25",
        )
    ax.set_xlim(minimum, maximum)
    ax.set_ylim(len(rows) - 0.5, -0.55)
    ax.set_yticks(range(len(rows)), [row["task"] for row in rows], fontsize=12.5)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1] if physics else [0.5, 0.6, 0.7, 0.8, 0.9])
    ax.tick_params(length=0, pad=7, labelsize=11)
    ax.grid(axis="x", color="#E3EAEF", linewidth=0.8, zorder=0)
    for side in ("top", "left", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.set_xlabel(section["metric"], fontsize=12, labelpad=6)
    ax.text(1.07, 1.025, "Score", transform=ax.transAxes, ha="center", color=SOFT, fontsize=10)
    ax.text(
        1.26,
        1.025,
        "Δ R²" if physics else "Δ AUPRC\n(percentage points)",
        transform=ax.transAxes,
        ha="center",
        color=SOFT,
        fontsize=9.5,
    )
    for extension in ("svg", "png"):
        fig.savefig(
            output / f"{key}.{extension}",
            dpi=220,
            metadata={"Date": None} if extension == "svg" else None,
        )
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(__file__).with_name("data.json").read_text())
    plt.rcParams.update(
        {
            "font.family": ["Nimbus Sans", "DejaVu Sans"],
            "font.size": 12,
            "text.color": INK,
            "axes.labelcolor": SOFT,
            "xtick.color": SOFT,
            "ytick.color": INK,
            "svg.fonttype": "path",
            "svg.hashsalt": "siderius-results",
        }
    )
    for key in ("physics", "cancer"):
        render_panel(key, data[key], args.output_dir)


if __name__ == "__main__":
    main()
