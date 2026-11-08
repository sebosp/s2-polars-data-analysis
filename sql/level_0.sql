-- Level 0: inspect the snapshot. Each block is also a view: FROM level_0.rows

-- @query rows frame=rows
-- How many rows has each table?
SELECT 'details' AS "table", count(*) AS rows FROM details
UNION ALL SELECT 'stats', count(*) FROM stats
UNION ALL SELECT 'upgrades', count(*) FROM upgrades
UNION ALL SELECT 'unit_born', count(*) FROM unit_born
UNION ALL SELECT 'unit_died', count(*) FROM unit_died
UNION ALL SELECT 'cmd_target_point', count(*) FROM cmd_target_point
UNION ALL SELECT 'cmd_target_unit', count(*) FROM cmd_target_unit
UNION ALL SELECT 'cmd_no_target', count(*) FROM cmd_no_target;

-- @query span frame=span
-- How many games, from when to when, on how many maps?
SELECT
    count(DISTINCT ext_fs_id) AS games,
    count(*) AS player_rows,
    min(ext_datetime) AS first_game,
    max(ext_datetime) AS last_game,
    count(DISTINCT ext_datetime::DATE) AS days_with_games,
    count(DISTINCT title) AS maps,
    count(DISTINCT player_name) AS player_names
FROM details;

-- @query race_spellings frame=races
-- Every localized spelling of a race, mapped to T, Z or P.
SELECT d.player_race, coalesce(r.letter, '?') AS race, count(*) AS player_rows
FROM details d
LEFT JOIN races r ON r.race = d.player_race
GROUP BY ALL
ORDER BY player_rows DESC;

-- @query shapes frame=shapes
-- How many players, observers and computers do the games have?
WITH per_game AS (
    SELECT
        ext_fs_id,
        count(*) FILTER (WHERE player_observe = 0) AS players,
        count(*) FILTER (WHERE player_observe <> 0) AS observers,
        count(*) FILTER (WHERE player_control = 3) AS computers,
        count(DISTINCT player_team_id) AS teams
    FROM details
    GROUP BY ext_fs_id
)
SELECT players, observers, computers, teams, count(*) AS games
FROM per_game
GROUP BY ALL
ORDER BY games DESC;

-- @query stats_summary
-- Minimum, maximum, quartiles and nulls of the main columns of the stats.
SELECT * FROM (
    SUMMARIZE SELECT ext_replay_loop, workers_active_count, minerals_collection_rate, vespene_collection_rate, minerals_current, food_used, food_made
    FROM stats
);

-- @query checks frame=checks
-- Sanity checks: a false is a fact about the data to remember.
SELECT 'one id per replay file' AS "check", count(DISTINCT ext_fs_id) = count(DISTINCT ext_fs_sha256) AS ok FROM details
UNION ALL
SELECT 'every game dated', bool_and(ext_datetime IS NOT NULL) FROM details
UNION ALL
SELECT 'one winner and one loser per game', bool_and(wins = 1 AND losses >= 1)
FROM (
    SELECT ext_fs_id, count(*) FILTER (WHERE player_result = 'Win') AS wins, count(*) FILTER (WHERE player_result = 'Loss') AS losses
    FROM details WHERE player_observe = 0 GROUP BY ext_fs_id
)
UNION ALL
SELECT 'every player mapped to a tracker id', bool_and(coalesce(mapped, 0) = players)
FROM (SELECT ext_fs_id, count(*) FILTER (WHERE player_observe = 0) AS players FROM details GROUP BY ext_fs_id) d
LEFT JOIN (SELECT ext_fs_id, count(*) AS mapped FROM players GROUP BY ext_fs_id) p USING (ext_fs_id);

-- @query durations frame=durations
-- How long each game lasted, in minutes at Faster speed.
SELECT ext_fs_id, game_seconds(max(ext_replay_loop)) / 60 AS minutes FROM stats GROUP BY ext_fs_id;
