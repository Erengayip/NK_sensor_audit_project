"""Запуск проекта. Команда: python run.py."""

import json
import sqlite3
from contextlib import closing
from urllib.error import URLError

from analysis import benchmark, compare_versions, eda, known_issues, load_queries, sql_results
from etl import DB, RESULTS, load_releases, make_database, make_wide
from visuals import correlation_plot, coverage_plot, diurnal_plot, known_issues_plot


def main():
    long, v1 = load_releases()
    wide = make_wide(long)
    RESULTS.mkdir(exist_ok=True)
    plots = RESULTS / "figures"
    plots.mkdir(exist_ok=True)
    make_database(DB, long, wide)
    start, end = long["timestamp"].min(), long["timestamp"].max()
    queries = load_queries()
    versions, differences, metadata = compare_versions(long, v1)
    with closing(sqlite3.connect(DB)) as con:
        results = sql_results(con, queries, start, end)
        results["method_comparison"] = benchmark(con, long, queries["gaps"])
    if results["gaps"]["missing_hours"].sum() != results["coverage"]["missing_hours"].sum():
        raise ValueError("LAG and coverage totals disagree")
    area, shift = known_issues(long)
    descriptive, diurnal, matrices = eda(long)
    results.update({
        "version_comparison": versions, "version_top_differences": differences,
        "area_monthly_medians": area, "area_may_shift": shift,
        "eda_descriptive": descriptive, "eda_diurnal": diurnal,
    })
    for well_type, (corr, counts) in matrices.items():
        results[f"corr_{well_type}"] = corr.reset_index()
        results[f"corr_n_{well_type}"] = counts.reset_index()
    for name, frame in results.items():
        frame.to_csv(RESULTS / f"{name}.csv", index=False, encoding="utf-8-sig")
    metadata.update({
        "start": str(start), "end": str(end), "long_rows": len(long), "wide_rows": len(wide),
        "wells": int(long["well_id"].nunique()), "duplicate_v2_keys": 0,
        "flagged_rows": int(long["flag"].notna().sum()), "sql_queries": len(queries),
    })
    (RESULTS / "summary.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    coverage_plot(results["coverage"], plots / "01_coverage.png")
    diurnal_plot(diurnal, plots / "02_diurnal.png")
    correlation_plot(matrices, plots / "03_correlations.png")
    known_issues_plot(area, long, plots / "04_known_issues.png")
    print(f"SQLite: {DB}")
    print(f"Long: {len(long):,} | Wide: {len(wide):,} | SQL reports: {len(queries)}")
    print(results["method_comparison"].to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except URLError as error:
        raise SystemExit(f"Не удалось скачать данные. Ссылки и ручная загрузка указаны в README. {error}") from error
