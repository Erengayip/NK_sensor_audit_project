-- name: gaps
-- Полезная точка = час с числовым value. Границы добавляют крайние пропуски.
WITH points AS (
  SELECT well_id, parameter, timestamp
  FROM observations
  WHERE timestamp BETWEEN :start AND :end AND value IS NOT NULL
  UNION ALL
  SELECT well_id, parameter, datetime(:start, '-1 hour') FROM sensors
  UNION ALL
  SELECT well_id, parameter, datetime(:end, '+1 hour') FROM sensors
), ordered AS (
  SELECT *, LAG(timestamp) OVER (
    PARTITION BY well_id, parameter ORDER BY timestamp
  ) AS previous_hour
  FROM points
), intervals AS (
  SELECT well_id, parameter, datetime(previous_hour, '+1 hour') AS gap_start,
         datetime(timestamp, '-1 hour') AS gap_end,
         (unixepoch(timestamp) - unixepoch(previous_hour)) / 3600 - 1 AS missing_hours
  FROM ordered
)
SELECT * FROM intervals WHERE missing_hours > 0
ORDER BY well_id, parameter, gap_start;

-- name: monthly
SELECT o.well_id, w.well_type, o.parameter, substr(o.timestamp, 1, 7) AS month,
       COUNT(*) AS rows_present, COUNT(o.value) AS numeric_hours, AVG(o.value) AS mean_value,
       MIN(o.value) AS min_value, MAX(o.value) AS max_value, AVG(o.n_obs) AS mean_n_obs,
       SUM(o.flag IS NOT NULL) AS flagged_rows
FROM observations AS o JOIN wells AS w USING (well_id)
GROUP BY o.well_id, w.well_type, o.parameter, month
ORDER BY o.well_id, o.parameter, month;

-- name: coverage
WITH audit_window AS (
  SELECT (unixepoch(MAX(timestamp)) - unixepoch(MIN(timestamp))) / 3600 + 1 AS hours
  FROM hourly_wide
)
SELECT s.well_id, w.well_type, s.parameter, s.unit, hours AS expected_hours,
       COUNT(o.timestamp) AS rows_present,
       hours - COUNT(o.timestamp) AS absent_rows,
       COUNT(o.timestamp) - COUNT(o.value) AS null_values,
       hours - COUNT(o.value) AS missing_hours,
       ROUND(100.0 * (hours - COUNT(o.value)) / hours, 4) AS missing_pct
FROM sensors AS s JOIN wells AS w USING (well_id)
CROSS JOIN audit_window
LEFT JOIN observations AS o USING (well_id, parameter)
GROUP BY s.well_id, s.parameter
ORDER BY missing_hours DESC, s.well_id, s.parameter;

-- name: flag_tokens
SELECT flag, COUNT(*) AS flagged_hours
FROM quality_flags GROUP BY flag ORDER BY flagged_hours DESC, flag;

-- name: flag_combinations
SELECT COALESCE(flag, '(пусто)') AS flag, COUNT(*) AS hourly_rows
FROM observations GROUP BY flag ORDER BY hourly_rows DESC;

-- name: split_summary
SELECT split, MIN(timestamp) AS start_at, MAX(timestamp) AS end_at,
       COUNT(*) AS rows_present, COUNT(DISTINCT well_id) AS wells,
       SUM(flag IS NOT NULL) AS flagged_rows
FROM observations GROUP BY split ORDER BY start_at;

-- name: common_outages
WITH silent_hours AS (
  SELECT timestamp
  FROM hourly_wide
  GROUP BY timestamp
  HAVING SUM(SPM IS NOT NULL OR casing_pressure IS NOT NULL
             OR dynamometer_area IS NOT NULL OR line_pressure IS NOT NULL
             OR max_rod_weight IS NOT NULL OR min_rod_weight IS NOT NULL
             OR pump_fillage IS NOT NULL OR tubing_pressure IS NOT NULL) = 0
), islands AS (
  SELECT timestamp, unixepoch(timestamp) / 3600 - ROW_NUMBER() OVER (ORDER BY timestamp) AS island
  FROM silent_hours
)
SELECT MIN(timestamp) AS outage_start, MAX(timestamp) AS outage_end, COUNT(*) AS hours
FROM islands GROUP BY island ORDER BY hours DESC, outage_start;

-- name: observation_counts
SELECT w.well_type, o.parameter, MIN(o.n_obs) AS min_raw_count,
       AVG(o.n_obs) AS avg_raw_count, MAX(o.n_obs) AS max_raw_count,
       SUM(o.n_obs = 1) AS one_raw_count
FROM observations AS o JOIN wells AS w USING (well_id)
GROUP BY w.well_type, o.parameter ORDER BY w.well_type, o.parameter;

-- name: flag_hotspots
SELECT well_id, parameter, substr(timestamp, 1, 7) AS month, COUNT(*) AS flagged_rows
FROM observations WHERE flag IS NOT NULL
GROUP BY well_id, parameter, month HAVING COUNT(*) >= 10
ORDER BY flagged_rows DESC, well_id, parameter, month;

-- name: nk7_regime
SELECT CASE WHEN timestamp < '2026-06-01' THEN 'jan_may' ELSE 'jun_sep' END AS period,
       parameter, COUNT(value) AS n, AVG(value) AS mean_value,
       ROUND(100.0 * SUM(value = 0) / COUNT(value), 4) AS zero_pct,
       ROUND(100.0 * SUM(value < 0) / COUNT(value), 4) AS negative_pct
FROM observations
WHERE well_id = 'NK-7' AND parameter IN ('SPM', 'dynamometer_area')
GROUP BY period, parameter ORDER BY MIN(timestamp), parameter;
