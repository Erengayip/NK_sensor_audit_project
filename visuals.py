"""Четыре статических рисунка для отчёта."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

INK = "#173044"
TEAL = "#087F80"
ORANGE = "#B54F26"
PAPER = "#FFFFFF"
GRID = "#DDE8EB"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.labelcolor": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": GRID, "xtick.color": INK, "ytick.color": INK,
    "grid.color": GRID, "figure.facecolor": PAPER,
})
SHORT = {
    "casing_pressure": "casing", "line_pressure": "line", "tubing_pressure": "tubing",
    "dynamometer_area": "area", "max_rod_weight": "max weight", "min_rod_weight": "min weight",
    "pump_fillage": "fillage", "SPM": "SPM",
}


def save(fig, path):
    fig.savefig(path, dpi=180, bbox_inches="tight", pad_inches=0.12, facecolor=PAPER)
    plt.close(fig)


def coverage_plot(coverage, path):
    top = coverage.nlargest(12, "missing_pct").sort_values("missing_pct")
    labels = top["well_id"] + "  /  " + top["parameter"].map(SHORT)
    fig, ax = plt.subplots(figsize=(8.7, 4.3), layout="constrained")
    bars = ax.barh(labels, top["missing_pct"], color=TEAL, height=0.67)
    ax.bar_label(bars, fmt="%.1f%%", padding=4, fontsize=9)
    ax.set(xlim=(0, top["missing_pct"].max() * 1.20), xlabel="Доля часов без значения, %")
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)
    save(fig, path)


def diurnal_plot(diurnal, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.25), layout="constrained")
    options = [
        ("fountain", "tubing_pressure", "Фонтанные • tubing_pressure", "атм", TEAL),
        ("sucker_rod_pump", "SPM", "Штанговые • SPM", "ход/мин", ORANGE),
    ]
    for ax, (kind, parameter, title, unit, color) in zip(axes, options):
        series = diurnal.loc[diurnal["well_type"].eq(kind) & diurnal["parameter"].eq(parameter)]
        ax.plot(series["hour"], series["median"], marker="o", markersize=3.8, color=color)
        ax.axhline(0, color="#718795", linewidth=0.85)
        ax.set(title=title, xlabel="Час суток", ylabel=f"Медианное отклонение, {unit}",
               xticks=[0, 4, 8, 12, 16, 20, 23])
        ax.grid(axis="y")
    save(fig, path)


def correlation_plot(matrices, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), layout="constrained")
    image = None
    for ax, (kind, (matrix, _)) in zip(axes, matrices.items()):
        labels = [SHORT[column] for column in matrix.columns]
        image = ax.imshow(matrix, vmin=-1, vmax=1, cmap="RdBu_r")
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
        ax.set_yticks(range(len(labels)), labels)
        ax.set_title("Фонтанные" if kind == "fountain" else "Штанговые насосы")
        for i, j in np.ndindex(matrix.shape):
            value = matrix.iat[i, j]
            ax.text(j, i, f"{value:.2f}" if pd.notna(value) else "—",
                    color="white" if abs(value) > 0.64 else INK, ha="center", va="center", fontsize=9)
    fig.colorbar(image, ax=axes, fraction=0.045, pad=0.02, label="r Пирсона")
    save(fig, path)


def known_issues_plot(area, long, path):
    fig, axes = plt.subplots(2, 1, figsize=(9, 5.5), layout="constrained")
    colors = ["#007F80", "#B54F26", "#3D6FAD", "#854D94", "#477747", "#984567", "#62594A"]
    months = pd.date_range("2026-01-01", "2026-09-01", freq="MS")
    for (well, series), color in zip(area.groupby("well_id"), colors):
        axes[0].plot(pd.to_datetime(series["month"]), series["median"], marker="o", markersize=3.5,
                     color=color, label=well)
    axes[0].axvspan(pd.Timestamp("2026-05-01"), pd.Timestamp("2026-06-01"), color="#E6F2F0")
    axes[0].set(title="Месячные медианы dynamometer_area", ylabel="усл. ед.")
    axes[0].legend(ncol=4, frameon=False, loc="upper left", fontsize=8)
    nk7 = long.loc[long["well_id"].eq("NK-7") & long["parameter"].eq("SPM")]
    daily = nk7.set_index("timestamp")["value"].resample("D").median()
    axes[1].plot(daily.index, daily, color=TEAL, linewidth=1.15)
    axes[1].axvline(pd.Timestamp("2026-06-01"), color=ORANGE, linestyle="--", linewidth=1.4)
    axes[1].set(title="Суточная медиана SPM на NK-7", ylabel="ход/мин")
    for ax in axes:
        ax.set(xlim=(months[0], pd.Timestamp("2026-09-30")), xticks=months,
               xticklabels=["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен"])
        ax.grid(axis="y")
    save(fig, path)
