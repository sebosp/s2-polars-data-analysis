-- Level 3: trends. A month counts with at least 10 games, a series with at least 5 months.

-- @query series frame=series
-- Three monthly families: the workers at 8:00, the second townhall, the length of the games.
WITH at_8 AS (
    SELECT ext_fs_id, player_id, arg_min(workers_active_count, ext_replay_loop) AS value
    FROM stats
    WHERE floor(game_seconds(ext_replay_loop) / 60)::INTEGER = 8
    GROUP BY ALL
),
expansion AS (
    SELECT ext_fs_id, control_player_id AS player_id, min(game_seconds(ext_replay_loop)) AS value
    FROM unit_born
    WHERE ext_replay_loop > 0 AND unit_type_name IN ('Nexus', 'CommandCenter', 'Hatchery')
    GROUP BY ALL
),
monthly AS (
    SELECT 'workers_at_8' AS series, p.race AS entity, date_trunc('month', p.ext_datetime) AS month, count(*) AS games, median(a.value) AS value
    FROM at_8 a JOIN players p USING (ext_fs_id, player_id) GROUP BY ALL
    UNION ALL
    SELECT 'expansion_seconds', p.race, date_trunc('month', p.ext_datetime), count(*), median(e.value)
    FROM expansion e JOIN players p USING (ext_fs_id, player_id) GROUP BY ALL
    UNION ALL
    SELECT 'minutes', matchup, date_trunc('month', ext_datetime), count(*), median(minutes)
    FROM games GROUP BY ALL
),
kept AS (SELECT * FROM monthly WHERE games >= at_least(10) AND entity <> '?')
SELECT
    series, entity, month, games, value,
    date_diff('month', min(month) OVER (PARTITION BY series, entity), month) AS t
FROM kept
QUALIFY count(*) OVER (PARTITION BY series, entity) >= 5
ORDER BY series, entity, month;

-- @query trends frame=trends cols=series,entity,months,slope_per_month
-- The slope per month of every series with its standard error and t statistic: |t| under 2 is no trend.
SELECT
    series, entity,
    count(*) AS months,
    regr_slope(value, t) AS slope_per_month,
    regr_r2(value, t) AS r2,
    regr_slope(value, t) / sqrt((1 - regr_r2(value, t)) * var_samp(value) / var_samp(t) / (count(*) - 2)) AS t_statistic
FROM level_3.series
GROUP BY ALL
ORDER BY abs(t_statistic) DESC;

-- @query smoothed frame=smoothed cols=series,entity,month,rolling_3
-- The 3-month rolling mean of every series.
SELECT
    series, entity, month,
    avg(value) OVER (PARTITION BY series, entity ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3
FROM level_3.series;

-- @query regular frame=regular
-- A regular series for forecasting: the months without games get the previous value.
WITH bounds AS (
    SELECT series, entity, min(month)::TIMESTAMP AS first_month, max(month)::TIMESTAMP AS last_month
    FROM level_3.series
    GROUP BY ALL
),
months AS (
    SELECT series, entity, unnest(generate_series(first_month, last_month, INTERVAL 1 MONTH)) AS month FROM bounds
)
SELECT
    m.series, m.entity, m.month,
    last_value(s.value IGNORE NULLS) OVER (PARTITION BY m.series, m.entity ORDER BY m.month) AS value
FROM months m
LEFT JOIN level_3.series s ON s.series = m.series AND s.entity = m.entity AND s.month::TIMESTAMP = m.month;
