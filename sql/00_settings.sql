-- The choices of the examples, as views: replace one to follow another game, player or map, i.e.
--   CREATE OR REPLACE VIEW chosen_player AS SELECT 'Serral' AS player;
-- They are read by the views of the levels, so the whole level follows.

-- The player with the most games. On a snapshot of your replays, that is you.
CREATE OR REPLACE VIEW chosen_player AS
SELECT player FROM players GROUP BY player ORDER BY count(*) DESC, player LIMIT 1;

-- The latest 1v1 of that player.
CREATE OR REPLACE VIEW chosen_game AS
SELECT ext_fs_id FROM games_1v1 WHERE player = (FROM chosen_player) ORDER BY ext_datetime DESC LIMIT 1;

-- The 15 players with the most 1v1 games.
CREATE OR REPLACE VIEW top_players AS
SELECT player FROM games_1v1 GROUP BY player HAVING count(*) >= at_least(30) ORDER BY count(*) DESC, player LIMIT 15;

-- The 20 most played maps, at least 20 games each.
CREATE OR REPLACE VIEW top_maps AS
SELECT title FROM games GROUP BY title HAVING count(*) >= at_least(20) ORDER BY count(*) DESC, title LIMIT 20;

-- The most played map.
CREATE OR REPLACE VIEW chosen_map AS SELECT title FROM top_maps LIMIT 1;

-- Units that expire or die on their own, not because a player killed them.
CREATE OR REPLACE VIEW expires AS
SELECT unnest(['InvisibleTargetDummy', 'Larva', 'Egg', 'Broodling', 'BroodlingEscort', 'AdeptPhaseShift', 'ForceField', 'KD8Charge', 'CreepTumorBurrowed']) AS name;

-- Units born with a creator ability that are not army.
CREATE OR REPLACE VIEW not_army AS
SELECT unnest(['Probe', 'SCV', 'Drone', 'Overlord', 'Larva', 'Egg', 'MULE', 'Broodling', 'BroodlingEscort', 'Interceptor', 'Changeling', 'AdeptPhaseShift', 'LocustMP', 'AutoTurret', 'KD8Charge', 'ParasiticBombDummy']) AS name;
