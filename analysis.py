"""Аудит, сравнение методов и разведочный анализ."""

from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd

from etl import HOUR, KEY, ROOT, SPLIT

GAP_COLUMNS = ["well_id", "parameter", "gap_start", "gap_end", "missing_hours"]


def load_queries():
    sql = (ROOT / "queries.sql").read_text(encoding="utf-8")
    queries = {}
    for block in sql.split("-- name: ")[1:]:
        name, statement = block.split("\n", maxsplit=1)
        queries[name] = statement.strip()
    return queries


def sql_results(con, queries, start, end):
    bounds = {"start": str(start), "end": str(end)}
    return {name: pd.read_sql_query(sql, con, params=bounds) for name, sql in queries.items()}


def grid_gaps(series, start, end):
    # Базовый метод явно проверяет каждый час календарной сетки.
    grid = pd.date_range(start, end, freq="h")
    intervals = []
    for (well, parameter), hours in series.items():
        missing = ~grid.isin(hours)
        edges = np.diff(np.r_[False, missing, False].astype(np.int8))
        for first, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            intervals.append((well, parameter, grid[first], grid[stop - 1], stop - first))
    return pd.DataFrame(intervals, columns=GAP_COLUMNS)


def diff_gaps(series, start, end):
    # Сравниваем только соседние фактические метки и две границы.
    intervals = []
    for (well, parameter), hours in series.items():
        points = pd.DatetimeIndex([start - HOUR]).append(hours).append(pd.DatetimeIndex([end + HOUR]))
        widths = (points[1:] - points[:-1]) // HOUR - 1
        for i in np.flatnonzero(widths > 0):
            intervals.append((well, parameter, points[i] + HOUR, points[i + 1] - HOUR, widths[i]))
    return pd.DataFrame(intervals, columns=GAP_COLUMNS)


def gap_keys(frame):
    frame = frame.copy()
    for column in ["gap_start", "gap_end"]:
        frame[column] = pd.to_datetime(frame[column])
    return set(frame[GAP_COLUMNS].itertuples(index=False, name=None))


def benchmark(con, long, gap_sql, repeats=7):
    first, last = long["timestamp"].min(), long["timestamp"].max()
    pairs = sorted(set(long[["well_id", "parameter"]].itertuples(index=False, name=None)))
    results = []
    for split, start, end in [("train", first, SPLIT - HOUR), ("test", SPLIT, last)]:
        numeric = long.loc[long["split"].eq(split) & long["value"].notna()]
        prepared = {key: pd.DatetimeIndex(group["timestamp"]).sort_values()
                    for key, group in numeric.groupby(["well_id", "parameter"])}
        series = {key: prepared.get(key, pd.DatetimeIndex([])) for key in pairs}
        bounds = {"start": str(start), "end": str(end)}
        methods = {
            "Grid (baseline)": lambda: grid_gaps(series, start, end),
            "Pandas diff": lambda: diff_gaps(series, start, end),
            "SQLite LAG": lambda: pd.read_sql_query(gap_sql, con, params=bounds),
        }
        truth = gap_keys(methods["Grid (baseline)"]())
        expected_missing = len(pairs) * ((end - start) // HOUR + 1) - len(numeric)
        if sum(gap[-1] for gap in truth) != expected_missing:
            raise ValueError(f"Calendar and observed counts disagree on {split}")
        for method, run in methods.items():
            predicted = gap_keys(run())
            matches = len(predicted & truth)
            if predicted != truth:
                raise ValueError(f"Gap interval mismatch: {split}, {method}")
            timings = []
            for _ in range(repeats):
                started = perf_counter()
                run()
                timings.append(1000 * (perf_counter() - started))
            results.append({
                "split": split, "method": method, "intervals": len(predicted),
                "missing_hours": sum(x[-1] for x in predicted),
                "precision": matches / len(predicted) if predicted else 1.0,
                "recall": matches / len(truth) if truth else 1.0,
                "median_ms": median(timings), "repeats": repeats,
            })
    return pd.DataFrame(results)


def compare_versions(v2, v1):
    start = max(v1["timestamp"].min(), v2["timestamp"].min())
    end = min(v1["timestamp"].max(), v2["timestamp"].max())
    columns = [*KEY, "value", "unit", "well_type"]
    left = v1.loc[v1["timestamp"].between(start, end), columns]
    right = v2.loc[v2["timestamp"].between(start, end), columns]
    duplicate_v1 = int(left.duplicated(KEY).sum())
    if duplicate_v1:
        # Ключ с несколькими строками неоднозначен для сравнения значений.
        raise ValueError(f"{duplicate_v1} duplicate v1 keys in shared window")
    joined = left.merge(right, on=KEY, how="outer", indicator=True,
                        suffixes=("_v1", "_v2"), validate="one_to_one")
    joined["paired"] = joined["_merge"].eq("both")
    joined["comparable"] = (joined["paired"] & joined["unit_v1"].eq(joined["unit_v2"])
                            & joined["value_v1"].notna() & joined["value_v2"].notna())
    joined["abs_diff"] = (joined["value_v2"] - joined["value_v1"]).abs().where(joined["comparable"])
    joined["rounding_match"] = joined["abs_diff"].le(0.00005001)
    joined["only_v1"] = joined["_merge"].eq("left_only")
    joined["only_v2"] = joined["_merge"].eq("right_only")
    joined["metadata_diff"] = joined["paired"] & (
        ~joined["unit_v1"].eq(joined["unit_v2"]) | ~joined["well_type_v1"].eq(joined["well_type_v2"])
    )
    aggregations = dict(
        common_keys=("paired", "sum"), only_v1=("only_v1", "sum"), only_v2=("only_v2", "sum"),
        metadata_diff=("metadata_diff", "sum"), comparable=("comparable", "sum"),
        rounding_match=("rounding_match", "sum"), median_abs_diff=("abs_diff", "median"),
        mae=("abs_diff", "mean"), max_abs_diff=("abs_diff", "max"),
    )
    grouped = joined.groupby("parameter").agg(**aggregations).reset_index()
    sample = joined.loc[joined["abs_diff"].nlargest(25).index, [
        *KEY, "unit_v1", "value_v1", "value_v2", "abs_diff"
    ]]
    return grouped, sample, {"overlap_start": str(start), "overlap_end": str(end), "v1_rows": len(v1)}


def known_issues(long):
    area = long.loc[long["parameter"].eq("dynamometer_area")].copy()
    area["month"] = area["timestamp"].dt.strftime("%Y-%m")
    monthly = area.groupby(["well_id", "month"])["value"].agg(n="count", median="median").reset_index()
    before = area.loc[area["timestamp"].lt("2026-05-01")].groupby("well_id")["value"].median()
    may = area.loc[area["month"].eq("2026-05")].groupby("well_id")["value"].median()
    shift = pd.DataFrame({"jan_apr_median": before, "may_median": may})
    shift["may_to_jan_apr"] = shift["may_median"] / shift["jan_apr_median"]
    return monthly, shift.reset_index()


def eda(long):
    # Сохраняем исходные строки для аудита. Для EDA используем часы без flag.
    clean = long.loc[long["flag"].isna() & long["value"].notna()].copy()
    grouped = clean.groupby(["well_type", "parameter", "unit"])["value"]
    descriptive = grouped.describe().reset_index()
    clean["month"] = clean["timestamp"].dt.strftime("%Y-%m")
    clean["hour"] = clean["timestamp"].dt.hour
    # Для суточного профиля и корреляций убираем различия базового уровня.
    group = ["well_id", "parameter", "month"]
    clean["centered"] = clean["value"] - clean.groupby(group)["value"].transform("median")
    diurnal = clean.groupby(["well_type", "parameter", "unit", "hour"])["centered"].agg(
        n="count", median="median"
    ).reset_index()
    stable = clean.loc[
        ~clean["parameter"].eq("dynamometer_area") |
        (~clean["month"].eq("2026-05") & ~(clean["well_id"].eq("NK-7") & clean["month"].ge("2026-06")))
    ]
    matrices = {}
    for well_type, subset in stable.groupby("well_type"):
        wide = subset.pivot(index=["well_id", "timestamp"], columns="parameter", values="centered")
        valid = wide.notna().astype("int64")
        matrices[well_type] = (wide.corr(method="pearson", min_periods=48), valid.T @ valid)
    return descriptive, diurnal, matrices
