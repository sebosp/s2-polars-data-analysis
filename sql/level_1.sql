-- Level 1: one game, minute by minute. The game is the view chosen_game, see 00_settings.sql.

-- @query game frame=game
-- The chosen game.
SELECT ext_fs_id, ext_datetime, title, player, race, player_result, opponent, opponent_race, matchup
FROM games_1v1
WHERE player = (FROM chosen_player) AND ext_fs_id = (FROM chosen_game);

-- @query sides frame=sides
-- The two players, with the ids the tracker events and the commands use.
SELECT player_id, player_name, player, race, player_result FROM games_1v1 WHERE ext_fs_id = (FROM chosen_game);

-- @query economy frame=economy
-- Workers, income, unspent, army and supply of both players, one sample every 7 seconds.
SELECT
    p.player,
    p.race,
    game_seconds(s.ext_replay_loop) / 60 AS minute,
    s.workers_active_count AS workers,
    s.minerals_collection_rate + s.vespene_collection_rate AS income,
    s.minerals_current + s.vespene_current AS unspent,
    s.minerals_used_current_army + s.vespene_used_current_army AS army,
    s.food_used AS supply,
    s.food_made AS supply_cap
FROM stats s
JOIN level_1.sides p USING (player_id)
WHERE s.ext_fs_id = (FROM chosen_game);

-- @query blocked frame=blocked
-- Supply blocks: supply used at the cap, under 200.
SELECT
    player,
    count(*) AS blocked_samples,
    round(min(minute), 1) AS first_block_minute,
    round(max(minute), 1) AS last_block_minute,
    round(count(*) * 160 / 22.4, 0) AS blocked_seconds
FROM level_1.economy
WHERE supply >= supply_cap AND supply_cap < 200
GROUP BY player;

-- @query spending frame=spending
-- The spending quotient of TeamLiquid, from minute 2: 35 (0.00137 income - ln unspent) + 240.
SELECT
    player,
    avg(income) AS avg_income,
    avg(unspent) AS avg_unspent,
    max(workers) AS max_workers,
    max(supply) AS max_supply,
    35 * (0.00137 * avg(income) - ln(avg(unspent))) + 240 AS spending_quotient
FROM level_1.economy
WHERE minute >= 2
GROUP BY player;

-- @query build frame=build
-- The first 15 structures of each player. round_even rounds 2.5 to 2 like polars, round would give 3.
SELECT
    p.player,
    b.unit_type_name AS structure,
    round_even(game_seconds(b.ext_replay_loop), 0) AS seconds,
    row_number() OVER (PARTITION BY p.player ORDER BY b.ext_replay_loop, b.unit_tag_index) AS n
FROM unit_born b
JOIN level_1.sides p ON p.player_id = b.control_player_id
WHERE b.ext_fs_id = (FROM chosen_game) AND b.ext_replay_loop > 0 AND b.unit_type_name IN (SELECT name FROM structures)
QUALIFY n <= 15;

-- @query researched frame=researched
-- When each upgrade finished, without the sprays and the rewards.
SELECT p.player, u.name AS upgrade, round_even(game_seconds(u.ext_replay_loop), 0) AS seconds
FROM upgrades u
JOIN level_1.sides p USING (player_id)
WHERE u.ext_fs_id = (FROM chosen_game) AND u.ext_replay_loop > 0 AND NOT regexp_matches(u.name, '^(Spray|Reward|GameHeart)');

-- @query lost frame=lost
-- The army value lost in each minute: the fights.
WITH per_minute AS (
    SELECT
        p.player,
        floor(game_seconds(s.ext_replay_loop) / 60)::INTEGER AS minute,
        max(s.minerals_lost_army + s.vespene_lost_army) AS lost_so_far
    FROM stats s
    JOIN level_1.sides p USING (player_id)
    WHERE s.ext_fs_id = (FROM chosen_game)
    GROUP BY ALL
)
SELECT player, minute, lost_so_far - lag(lost_so_far, 1, 0) OVER (PARTITION BY player ORDER BY minute) AS army_lost
FROM per_minute;

-- @query kills frame=kills
-- Who killed what.
SELECT p.player AS killer, d.unit_killer_name AS killer_unit, d.unit_died_name AS victim, count(*) AS kills
FROM unit_died d
JOIN level_1.sides p ON p.player_id = d.killer_player_id
WHERE d.ext_fs_id = (FROM chosen_game) AND d.unit_killer_name <> ''
GROUP BY ALL;

-- @query deaths frame=deaths
-- Where the units died, by who killed them.
SELECT p.player AS killed_by, d.x, d.y, d.unit_died_name AS unit, round_even(game_seconds(d.ext_replay_loop), 0) AS seconds
FROM unit_died d
JOIN level_1.sides p ON p.player_id = d.killer_player_id
WHERE d.ext_fs_id = (FROM chosen_game) AND d.unit_died_name NOT IN (FROM expires);

-- @query commands frame=commands
-- The ability commands per minute. Not the APM of the client: no selections, no camera.
SELECT
    p.player,
    floor(game_seconds(c.ext_replay_loop) / 60)::INTEGER AS minute,
    count(*) AS commands,
    count(*) FILTER (WHERE c.ability_name = 'attack') AS attack_commands
FROM casts c
JOIN level_1.sides p USING (player_name)
WHERE c.ext_fs_id = (FROM chosen_game)
GROUP BY ALL;
