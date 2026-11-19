"""Загрузка проверенных источников и построение SQLite."""

import hashlib
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
DB = RESULTS / "nk_oil_wells.sqlite"
AUTHOR = "https://huggingface.co/datasets/Arailym-tleubayeva"
V2 = f"{AUTHOR}/NK-Oil-Well-Sensor-Monitoring-v2/resolve/4004bb78ca8811a87c2892a89e457c59d22ace2b"
V1 = f"{AUTHOR}/NK-Oil-Well-Sensor-Monitoring/resolve/84e5103cef58c85dc924e4b47aaed8ef2c5cb3dd"
SOURCES = {
    "train.csv": (f"{V2}/train.csv", "8bf92fd97ac9b0d7ec2e7aa61be90f335c7f3b6ab2a84634fb8758b057efe26a"),
    "test.csv": (f"{V2}/test.csv", "8029113613ea2965cb94fc7bea50eee6f4c327b673ecc856d88d25dfb652c7d6"),
    "v1.csv": (f"{V1}/wells_dataset.csv", "7a31fca2a4709a3bf9513bdc5fe7ed8f66a543a8d4e0c6855282ee8dde5f70b2"),
}
KEY = ["well_id", "parameter", "timestamp"]
HOUR = pd.Timedelta(hours=1)
SPLIT = pd.Timestamp("2026-08-08 23:00:00")


def source_file(name):
    url, expected = SOURCES[name]
    path = DATA / name
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        request = Request(url, headers={"User-Agent": "nk-well-audit/1.0"})
        print(f"Downloading {name}", flush=True)
        with urlopen(request, timeout=90) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch after downloading {name}")
        path.write_bytes(content)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {path}. Replace with the original from {url}")
    return path


def read_sensor_csv(name):
    df = pd.read_csv(source_file(name), parse_dates=["timestamp"])
    if df[KEY].isna().any().any() or not df["timestamp"].eq(df["timestamp"].dt.floor("h")).all():
        raise ValueError(f"Invalid key or timestamp in {name}")
    if np.isinf(df["value"]).any():
        raise ValueError(f"Infinite values in {name}")
    return df


def load_releases():
    train = read_sensor_csv("train.csv").assign(split="train")
    test = read_sensor_csv("test.csv").assign(split="test")
    v2 = pd.concat([train, test], ignore_index=True)
    if train["timestamp"].max() != SPLIT - HOUR or test["timestamp"].min() != SPLIT:
        raise ValueError("Unexpected source split boundary")
    if v2.duplicated(KEY).any() or v2["n_obs"].lt(1).any() or v2["n_obs"].isna().any():
        raise ValueError("v2 must have unique keys and positive n_obs")
    return v2, read_sensor_csv("v1.csv")


def make_wide(v2):
    # Одна строка на скважину и час, включая полностью пропущенные часы.
    hours = pd.date_range(v2["timestamp"].min(), v2["timestamp"].max(), freq="h")
    grid = pd.MultiIndex.from_product(
        [sorted(v2["well_id"].unique()), hours], names=["well_id", "timestamp"]
    )
    wide = v2.pivot(index=["well_id", "timestamp"], columns="parameter", values="value")
    wide = wide.reindex(grid).reset_index()
    wide.columns.name = None
    wide.insert(2, "split", np.where(wide["timestamp"].lt(SPLIT), "train", "test"))
    return wide


def make_database(path, long, wide):
    wells = long[["well_id", "well_type"]].drop_duplicates()
    sensors = long[["well_id", "parameter", "unit"]].drop_duplicates()
    observations = long[[*KEY, "split", "value", "n_obs", "flag"]]
    tagged = long.loc[long["flag"].notna(), [*KEY, "flag"]].copy()
    tagged["flag"] = tagged["flag"].str.split(";")
    tagged = tagged.explode("flag")
    # Временная база заменяет предыдущую только после завершения проверки.
    temporary = path.with_suffix(".building")
    temporary.unlink(missing_ok=True)
    con = sqlite3.connect(temporary)
    try:
        con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        for table, frame in (
            ("wells", wells), ("sensors", sensors), ("observations", observations),
            ("quality_flags", tagged), ("hourly_wide", wide),
        ):
            frame.to_sql(table, con, if_exists="append", index=False, chunksize=12_000)
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite foreign key check failed")
    finally:
        con.close()
    temporary.replace(path)
