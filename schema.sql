PRAGMA foreign_keys = ON;

CREATE TABLE wells (
    well_id TEXT PRIMARY KEY,
    well_type TEXT NOT NULL CHECK(well_type IN ('fountain', 'sucker_rod_pump'))
) WITHOUT ROWID;

CREATE TABLE sensors (
    well_id TEXT NOT NULL REFERENCES wells(well_id),
    parameter TEXT NOT NULL,
    unit TEXT NOT NULL,
    PRIMARY KEY (well_id, parameter)
) WITHOUT ROWID;

CREATE TABLE observations (
    well_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    split TEXT NOT NULL CHECK(split IN ('train', 'test')),
    value REAL,
    n_obs INTEGER NOT NULL CHECK(n_obs > 0),
    flag TEXT,
    PRIMARY KEY (well_id, parameter, timestamp),
    FOREIGN KEY (well_id, parameter) REFERENCES sensors(well_id, parameter)
) WITHOUT ROWID;

CREATE INDEX observations_split_time ON observations(split, timestamp);

CREATE TABLE quality_flags (
    well_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    flag TEXT NOT NULL,
    PRIMARY KEY (well_id, parameter, timestamp, flag),
    FOREIGN KEY (well_id, parameter, timestamp)
        REFERENCES observations(well_id, parameter, timestamp)
) WITHOUT ROWID;

CREATE TABLE hourly_wide (
    well_id TEXT NOT NULL REFERENCES wells(well_id),
    timestamp TEXT NOT NULL,
    split TEXT NOT NULL CHECK(split IN ('train', 'test')),
    SPM REAL,
    casing_pressure REAL,
    dynamometer_area REAL,
    line_pressure REAL,
    max_rod_weight REAL,
    min_rod_weight REAL,
    pump_fillage REAL,
    tubing_pressure REAL,
    PRIMARY KEY (well_id, timestamp)
) WITHOUT ROWID;
