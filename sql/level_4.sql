-- Level 4: compare the players. The player is the name without the clan tag, a name is not a person.

-- @query main_race frame=main_race
-- The race each player plays the most.
SELECT player, race AS main_race
FROM games_1v1
GROUP BY player, race
QUALIFY row_number() OVER (PARTITION BY player ORDER BY count(*) DESC, race) = 1;

-- @query leaderboard frame=leaderboard
-- Games, win rate and main race of the players with at least 30 1v1 games.
SELECT
    g.player,
    count(*) AS games,
    avg((g.player_result = 'Win')::INTEGER) AS win_rate,
    min(g.ext_datetime)::DATE AS first_game,
    max(g.ext_datetime)::DATE AS last_game,
    any_value(m.main_race) AS main_race
FROM games_1v1 g
JOIN level_4.main_race m USING (player)
GROUP BY g.player
HAVING count(*) >= at_least(30)
ORDER BY games DESC, g.player;

-- @query vs_race frame=vs_race
-- The win rate of the top players against each race.
SELECT player, opponent_race, count(*) AS games, avg((player_result = 'Win')::INTEGER) AS win_rate
FROM games_1v1
WHERE player IN (FROM top_players) AND opponent_race <> '?'
GROUP BY ALL
ORDER BY player, opponent_race;

-- @query head_to_head frame=head_to_head
-- The games between the top players.
SELECT player, opponent, count(*) AS games, count(*) FILTER (WHERE player_result = 'Win') AS wins
FROM games_1v1
WHERE player IN (FROM top_players) AND opponent IN (FROM top_players)
GROUP BY ALL
ORDER BY games DESC;

-- @query at_8
-- The workers and the income of every player of every game at 8:00.
SELECT
    s.ext_fs_id, s.player_id,
    arg_min(s.workers_active_count, s.ext_replay_loop) AS workers,
    arg_min(s.minerals_collection_rate + s.vespene_collection_rate, s.ext_replay_loop) AS income
FROM stats s
WHERE floor(game_seconds(s.ext_replay_loop) / 60)::INTEGER = 8
GROUP BY ALL;

-- @query field frame=field
-- The field: the median of all the players with a tracker id at 8:00.
SELECT median(a.workers) AS field_workers, median(a.income) AS field_income
FROM level_4.at_8 a
JOIN players p USING (ext_fs_id, player_id);

-- @query economy frame=economy
-- The median workers and income at 8:00 of the top players.
SELECT p.player, count(*) AS games_at_8, median(a.workers) AS median_workers, median(a.income) AS median_income, any_value(m.main_race) AS main_race
FROM level_4.at_8 a
JOIN players p USING (ext_fs_id, player_id)
JOIN level_4.main_race m USING (player)
WHERE p.player IN (FROM top_players)
GROUP BY p.player
ORDER BY median_income DESC;

-- @query commands frame=commands
-- The median ability commands per game minute of the top players.
WITH per_game AS (
    SELECT ext_fs_id, player_name, count(*) AS commands FROM casts GROUP BY ALL
)
SELECT p.player, count(*) AS games, median(c.commands / g.minutes) AS commands_per_minute
FROM per_game c
JOIN games g USING (ext_fs_id)
JOIN players p USING (ext_fs_id, player_name)
WHERE p.player IN (FROM top_players)
GROUP BY p.player
ORDER BY commands_per_minute DESC;

-- @query openings frame=openings
-- The first three structures of each game as one label, with the games and the win rate.
WITH first_structures AS (
    SELECT b.ext_fs_id, p.player, p.player_result, b.unit_type_name, b.ext_replay_loop, b.unit_tag_index
    FROM unit_born b
    JOIN games_1v1 p ON p.ext_fs_id = b.ext_fs_id AND p.player_id = b.control_player_id
    WHERE b.ext_replay_loop > 0 AND b.unit_type_name IN (SELECT name FROM structures) AND p.player IN (FROM top_players)
    QUALIFY row_number() OVER (PARTITION BY b.ext_fs_id, p.player_id ORDER BY b.ext_replay_loop, b.unit_tag_index) <= 3
),
per_game AS (
    SELECT ext_fs_id, player, player_result, string_agg(unit_type_name, ' > ' ORDER BY ext_replay_loop, unit_tag_index) AS opening
    FROM first_structures
    GROUP BY ALL
)
SELECT player, opening, count(*) AS games, avg((player_result = 'Win')::INTEGER) AS win_rate,
       count(*) / sum(count(*)) OVER (PARTITION BY player) AS share
FROM per_game
GROUP BY player, opening
ORDER BY player, games DESC, opening;

-- @query army frame=army
-- The share of the army units each top player makes.
SELECT p.player, b.unit_type_name AS unit, count(*) AS units, count(*) / sum(count(*)) OVER (PARTITION BY p.player) AS share
FROM unit_born b
JOIN games_1v1 p ON p.ext_fs_id = b.ext_fs_id AND p.player_id = b.control_player_id
WHERE b.ext_replay_loop > 0 AND b.creator_ability_name <> '' AND b.creator_ability_name IS NOT NULL
  AND b.unit_type_name NOT IN (FROM not_army) AND p.player IN (FROM top_players)
GROUP BY p.player, b.unit_type_name
ORDER BY player, units DESC, unit;
