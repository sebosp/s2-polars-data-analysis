-- Level 5: compare the maps. The maps are the view top_maps, see 00_settings.sql.

-- @query maps frame=maps
-- Games, dates and median length of the most played maps.
SELECT title, count(*) AS games, min(ext_datetime)::DATE AS first_game, max(ext_datetime)::DATE AS last_game, median(minutes) AS median_minutes
FROM games
WHERE title IN (FROM top_maps)
GROUP BY title
ORDER BY games DESC, title;

-- @query map_balance frame=map_balance
-- The win rate of the first race per map and matchup. The margin on 20 games is about 11 points.
SELECT
    title, matchup,
    count(*) AS games,
    avg((winner_race = matchup[1])::INTEGER) AS first_race_win_rate,
    avg((winner_race = matchup[1])::INTEGER) - 0.5 AS edge
FROM games
WHERE title IN (FROM top_maps) AND winner_race <> loser_race AND winner_race <> '?' AND loser_race <> '?'
GROUP BY ALL
HAVING count(*) >= at_least(20)
ORDER BY matchup, edge;

-- @query quartiles frame=quartiles_linear
-- The quartiles of the game length per map.
SELECT title, quantile_cont(minutes, 0.25) AS q25, median(minutes) AS median, quantile_cont(minutes, 0.75) AS q75, count(*) AS games
FROM games
WHERE title IN (FROM top_maps)
GROUP BY title
ORDER BY median;

-- @query expansions frame=expansions
-- The median time of the second and third townhall per map.
WITH ranked AS (
    SELECT b.ext_fs_id, g.title, b.control_player_id, game_seconds(b.ext_replay_loop) AS seconds,
           row_number() OVER (PARTITION BY b.ext_fs_id, b.control_player_id ORDER BY b.ext_replay_loop) AS n
    FROM unit_born b
    JOIN games g USING (ext_fs_id)
    WHERE b.ext_replay_loop > 0 AND b.unit_type_name IN ('Nexus', 'CommandCenter', 'Hatchery') AND g.title IN (FROM top_maps)
),
per_player AS (
    SELECT ext_fs_id, title, control_player_id,
           min(seconds) FILTER (WHERE n = 1) AS second_base, min(seconds) FILTER (WHERE n = 2) AS third_base
    FROM ranked
    GROUP BY ALL
)
SELECT title, count(*) AS players, median(second_base) AS median_second_base, median(third_base) AS median_third_base
FROM per_player
GROUP BY title
ORDER BY median_third_base;

-- @query cells frame=cells
-- Where the units die on the most played map, in cells of 8 by 8.
SELECT (x::INTEGER // 8) * 8 AS cell_x, (y::INTEGER // 8) * 8 AS cell_y, count(*) AS deaths
FROM unit_died
WHERE ext_fs_id IN (SELECT ext_fs_id FROM games WHERE title = (FROM chosen_map)) AND killer_player_id IS NOT NULL
  AND unit_died_name NOT IN (FROM expires)
GROUP BY ALL
ORDER BY deaths DESC;
