-- Level 2: many games, over the months. A month counts with at least 10 games.

-- @query per_month frame=per_month
-- Games, maps and player names per month.
SELECT
    date_trunc('month', ext_datetime) AS month,
    count(DISTINCT ext_fs_id) AS games,
    count(DISTINCT title) AS maps,
    count(DISTINCT player_name) AS player_names
FROM details
GROUP BY ALL
ORDER BY month;

-- @query balance frame=balance
-- The win rate of the first race of each matchup per month: PvT is the share the Protoss won.
SELECT
    matchup,
    date_trunc('month', ext_datetime) AS month,
    count(*) AS games,
    avg((player_result = 'Win')::INTEGER) AS win_rate
FROM games_1v1
WHERE race < opponent_race AND race <> '?' AND opponent_race <> '?'
GROUP BY ALL
HAVING count(*) >= at_least(10)
ORDER BY matchup, month;

-- @query length frame=length
-- The median game length per matchup and month.
SELECT matchup, date_trunc('month', ext_datetime) AS month, count(*) AS games, median(minutes) AS median_minutes
FROM games
GROUP BY ALL
HAVING count(*) >= at_least(10)
ORDER BY matchup, month;

-- @query benchmarks frame=benchmarks
-- The median workers and income at 6:00, 8:00 and 10:00, per race and month.
WITH at_minute AS (
    SELECT
        ext_fs_id,
        player_id,
        floor(game_seconds(ext_replay_loop) / 60)::INTEGER AS minute,
        arg_min(workers_active_count, ext_replay_loop) AS workers,
        arg_min(minerals_collection_rate + vespene_collection_rate, ext_replay_loop) AS income
    FROM stats
    WHERE floor(game_seconds(ext_replay_loop) / 60)::INTEGER IN (6, 8, 10)
    GROUP BY ALL
)
SELECT
    p.race,
    a.minute,
    date_trunc('month', p.ext_datetime) AS month,
    count(*) AS players,
    median(a.workers) AS median_workers,
    median(a.income) AS median_income
FROM at_minute a
JOIN players p USING (ext_fs_id, player_id)
WHERE p.race <> '?'
GROUP BY ALL
HAVING count(*) >= at_least(10)
ORDER BY race, minute, month;

-- @query upgrade_timing frame=upgrade_timing
-- The median game time at which key upgrades finished, per month.
SELECT
    u.name AS upgrade,
    date_trunc('month', p.ext_datetime) AS month,
    count(*) AS games,
    median(game_seconds(u.ext_replay_loop)) AS median_seconds
FROM upgrades u
JOIN players p USING (ext_fs_id, player_id)
WHERE u.name IN ('Stimpack', 'WarpGateResearch', 'zerglingmovementspeed', 'BlinkTech', 'Charge', 'GlialReconstitution')
  AND u.ext_replay_loop > 0
GROUP BY ALL
HAVING count(*) >= at_least(10)
ORDER BY upgrade, month;

-- @query map_months frame=map_months
-- The games per map and month: the map pool.
SELECT title, date_trunc('month', ext_datetime) AS month, count(*) AS games
FROM games
GROUP BY ALL
ORDER BY title, month;

-- @query inject_per_month frame=inject_per_month
-- The Injects per game of the Zerg players per month, from the usage tables of s2protocol-rs 5.1.
WITH games AS (
    SELECT period, sum(games) AS games
    FROM player_usage_month u JOIN races r ON r.race = u.player_race
    WHERE r.letter = 'Z'
    GROUP BY ALL
),
uses AS (
    SELECT period, sum(uses) AS uses
    FROM ability_usage_month u JOIN races r ON r.race = u.player_race
    WHERE r.letter = 'Z' AND ability = 'SpawnLarva.Execute'
    GROUP BY ALL
)
SELECT period, games, uses, uses / games AS per_game
FROM games JOIN uses USING (period)
WHERE games >= at_least(10)
ORDER BY period;
