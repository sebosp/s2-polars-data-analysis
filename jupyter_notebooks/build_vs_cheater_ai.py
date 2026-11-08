"""Writes the Vs_Cheater_AI.ipynb notebook, run it again after changing the cells:

    uv run python build_vs_cheater_ai.py && uv run jupyter nbconvert --to notebook --execute --inplace Vs_Cheater_AI.ipynb
"""

import nbformat as nbf

cells = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip("\n")))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip("\n")))


md(r"""
# My games vs Cheater AI

The games of the main player alone against two computers of the same difficulty and build, by
default **Cheater 3 (Insane)** with the **Economic Focus** build: what is played, how the games go
and what seems to make the difference between the wins and the losses.

- The main player comes from the *Main Player Name* of swarmy's Config, or `MAIN_PLAYER` below.
  The name is compared without the clan tag, `<chezs> Sazed` is `Sazed`.
- The difficulty and the build of the computers are the `lobby_slot_difficulty` and
  `lobby_slot_ai_build` columns of the details, written by s2protocol-rs since the branch
  `snapshot-seconds-and-compression`: 10 is Cheater 3 (Insane), build 5 is Macro, the
  *Economic Focus* of the game lobby.
- The times are game seconds at Faster speed, the in-game clock.
- The structures are counted when they are started, the units when they are born.
- The commands are the orders given, i.e. an Inject Larva commanded twice on the same Hatchery
  counts twice.
- What wins and losses have in common is correlation, not cause: the longer games have more of
  everything, so most comparisons are made at fixed minutes.
- The Cheater 3 (Insane) computers cheat: they see the whole map and they get far more resources
  than their workers could mine. Their income and army are not a target to match, the measures of
  the main player are compared between its own wins and losses. How much more the computers get is
  measured below, per worker.
""")

code(r"""
import json
from pathlib import Path

import plotly.express as px
import polars as pl

import snapshot as s2

pl.Config.set_tbl_width_chars(200)
pl.Config.set_tbl_rows(30)
pl.Config.set_fmt_str_lengths(60)

# The snapshot of the replays, written by s2protocol-rs `write-arrow-ipc` with the AI columns.
IPC_DIR = "~/SC2Replays/Sazed/ipcs-notebook"

# The Main Player Name of swarmy's Config, if set.
SWARMY_SETTINGS = Path("~/.local/share/com.swarmy/settings.json").expanduser()
settings = json.loads(SWARMY_SETTINGS.read_text()) if SWARMY_SETTINGS.exists() else {}
MAIN_PLAYER = settings.get("main_player_name") or "Sazed"

# Cheater 3 (Insane), Economic Focus.
AI_DIFFICULTY = 10
AI_BUILD = 5
AI_DIFFICULTIES = {1: "Very Easy", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Harder", 6: "Very Hard",
                   7: "Elite", 8: "Cheater 1 (Vision)", 9: "Cheater 2 (Resources)", 10: "Cheater 3 (Insane)"}
AI_BUILDS = {0: "Any", 1: "Random", 2: "Rush", 3: "Timing", 4: "Power", 5: "Economic Focus", 6: "Air"}

# Win and loss are two categories: the first two slots of the categorical palette, blue and
# orange, they stay apart for the color blind.
RESULT_COLORS = {"Win": "#2a78d6", "Loss": "#eb6834"}
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
TEMPLATE = "plotly_white"

print(f"Main player {MAIN_PLAYER}, computers {AI_DIFFICULTIES[AI_DIFFICULTY]} {AI_BUILDS[AI_BUILD]}")
""")

md(r"""
## The games

One row per game: the main player alone on its team against exactly two computers of the
difficulty and build. The tracker `player_id` of the main player comes from its starting
townhall, the computers have no name in the tracker events.
""")

code(r"""
details = s2.scan(IPC_DIR, "details").filter(pl.col("player_observe") == 0)

computers = details.filter(pl.col("player_control") == 3)
target_games = (
    details.group_by("ext_fs_id")
    .agg(
        pl.len().alias("players"),
        (pl.col("player_control") == 3).sum().alias("computers"),
        pl.col("player_race").filter(pl.col("player_control") == 3).sort().alias("ai_races"),
    )
    .filter((pl.col("players") == 3) & (pl.col("computers") == 2))
    .join(
        computers.group_by("ext_fs_id").agg(
            ((pl.col("lobby_slot_difficulty") == AI_DIFFICULTY) & (pl.col("lobby_slot_ai_build") == AI_BUILD))
            .all()
            .alias("is_target")
        ),
        on="ext_fs_id",
    )
    .filter(pl.col("is_target"))
)

starts = (
    s2.scan(IPC_DIR, "unit_born")
    .filter((pl.col("ext_replay_loop") == 0) & pl.col("unit_type_name").is_in(["Hatchery", "CommandCenter", "Nexus"]))
    .select("ext_fs_id", pl.col("control_player_id").alias("player_id"), "player_name")
)
durations = s2.scan(IPC_DIR, "stats").group_by("ext_fs_id").agg(
    (pl.col("ext_replay_loop").max() / s2.GAME_LOOPS_PER_SECOND).alias("duration")
)

games = (
    details.filter(s2.name_without_clan() == MAIN_PLAYER)
    .join(target_games, on="ext_fs_id", how="semi")
    .join(target_games.select("ext_fs_id", "ai_races"), on="ext_fs_id")
    .join(starts, on=["ext_fs_id", "player_name"])
    .join(durations, on="ext_fs_id")
    .select(
        "ext_fs_id",
        "player_name",
        "player_id",
        pl.col("player_race").alias("race"),
        pl.col("player_result").alias("result"),
        "title",
        "ext_datetime",
        "ext_protocol_version",
        "lobby_random_seed",
        pl.col("ai_races").list.join(" + "),
        "duration",
        pl.col("ext_fs_file_name").alias("file"),
    )
    .filter(pl.col("result").is_in(["Win", "Loss"]))
    .sort("ext_datetime")
    .collect()
)
# The game ids are few, the event scans filter on them.
game_ids = games["ext_fs_id"].to_list()
won = games.select("ext_fs_id", "result").lazy()
# The games that end before 10:00 are all losses, mostly left early: the comparisons of the
# wins and the losses are made with the games that reached 10:00.
FULL_GAME_SECONDS = 600
full_ids = games.filter(pl.col("duration") >= FULL_GAME_SECONDS)["ext_fs_id"].to_list()
print(f"{games.height} games, {games['result'].eq('Win').mean():.1%} won, "
      f"from {games['ext_datetime'].min():%Y-%m-%d} to {games['ext_datetime'].max():%Y-%m-%d}")
short = games.filter(pl.col("duration") < FULL_GAME_SECONDS)
if short.height:
    print(f"{short.height} games ended before 10:00, {short['result'].eq('Win').mean():.0%} of them won")
games.head()
""")

md("### Over time, by map and by the races of the computers")

code(r"""
by_month = (
    games.lazy()
    .group_by(pl.col("ext_datetime").dt.truncate("1mo").alias("month"))
    .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().alias("win_rate"))
    .sort("month")
    .collect()
)
fig = px.line(by_month, x="month", y="win_rate", markers=True, hover_data=["games"], template=TEMPLATE,
              title="Win rate by month", color_discrete_sequence=SERIES_COLORS)
fig.update_yaxes(tickformat=".0%", range=[0, 1])
fig.update_traces(line_width=2, marker_size=8)
fig.show()

by_map, by_races = pl.collect_all([
    games.lazy().group_by("title").agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"),
                                       pl.col("duration").median().truediv(60).round(1).alias("median_minutes"))
    .filter(pl.col("games") >= 10).sort("win_rate", descending=True),
    games.lazy().group_by("ai_races").agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"))
    .sort("games", descending=True),
])
display(by_map)
by_races
""")

md(r"""
### How long the games last

The losses that end early are the timings of the computers that were not held, the long games
are won or lost later.
""")

code(r"""
fig = px.histogram(games.with_columns((pl.col("duration") / 60).alias("minutes")), x="minutes", color="result",
                   nbins=60, barmode="overlay", opacity=0.75, template=TEMPLATE, color_discrete_map=RESULT_COLORS,
                   title="Game length, wins and losses")
fig.show()

(
    games.lazy()
    .with_columns(pl.col("duration").truediv(60).cut([10, 15, 20, 30, 45, 60]).alias("minutes"))
    .group_by("minutes")
    .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"))
    .sort("minutes")
    .collect()
)
""")

md(r"""
## Build order and opening

When the main player started each structure, the first time only, and the first army unit
made. The opening is the order of the first Spawning Pool, Extractor and expansion Hatchery
(or the first Barracks, Refinery and Command Center, Gateway, Assimilator and Nexus for the
other races).
""")

code(r"""
born = (
    s2.scan(IPC_DIR, "unit_born")
    .filter(pl.col("ext_fs_id").is_in(game_ids))
    .join(games.lazy().select("ext_fs_id", pl.col("player_id").alias("control_player_id")), on=["ext_fs_id", "control_player_id"], how="semi")
    .filter(~pl.col("unit_type_name").str.starts_with("Beacon"))
    # Burrowing, morphing back, etc register a unit again, a unit is counted once.
    .unique(["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], keep="first")
    .select("ext_fs_id", "unit_type_name", "creator_ability_name", s2.game_seconds())
)

OPENING = {
    "Zerg": {"SpawningPool": "Pool", "Extractor": "Gas", "Hatchery": "Hatch"},
    "Terran": {"Barracks": "Rax", "Refinery": "Gas", "CommandCenter": "CC"},
    "Protoss": {"Gateway": "Gate", "Assimilator": "Gas", "Nexus": "Nexus"},
}
opening_names = {name: label for race in OPENING.values() for name, label in race.items()}
WORKERS_SUPPLY = ["Drone", "SCV", "Probe", "Overlord", "Larva", "Egg", "Broodling", "MULE", "Queen", "Changeling",
                  "CreepTumor", "CreepTumorBurrowed", "CreepTumorQueen", "LocustMP", "LocustMPFlying", "InfestedTerransEgg",
                  "AdeptPhaseShift", "Interceptor", "AutoTurret", "KD8Charge", "ParasiticBombDummy", "RavagerCocoon",
                  "BanelingCocoon", "BroodLordCocoon", "OverlordCocoon", "TransportOverlordCocoon", "LurkerMPEgg",
                  "ForceField", "InvisibleTargetDummy", "BroodlingEscort"]


# Not the workers, supply, cocoons, nor the dummies and indicators of the map.
def is_unit():
    return ~pl.col("unit_type_name").is_in(WORKERS_SUPPLY) & ~pl.col("unit_type_name").str.contains("Dummy|Indicator")


openings = (
    born.filter(pl.col("unit_type_name").is_in(list(opening_names)) & (pl.col("game_seconds") > 0))
    .sort("game_seconds")
    .group_by("ext_fs_id")
    .agg(pl.col("unit_type_name").replace_strict(opening_names).unique(maintain_order=True).head(3).str.join("-").alias("opening"))
)
first_army = (
    # Army units are trained from larva or a production structure, not the initial ones.
    born.filter(pl.col("creator_ability_name").is_not_null() & is_unit())
    .sort("game_seconds")
    .group_by("ext_fs_id")
    .agg(pl.col("unit_type_name").first().alias("first_army_unit"), pl.col("game_seconds").first().alias("first_army_seconds"),
         pl.col("unit_type_name").mode().first().alias("most_made_unit"))
)
structures = ["SpawningPool", "Extractor", "RoachWarren", "BanelingNest", "Lair", "EvolutionChamber",
              "HydraliskDen", "Spire", "InfestationPit", "Hive", "LurkerDenMP", "UltraliskCavern", "GreaterSpire"]
structure_times = (
    born.filter(pl.col("unit_type_name").is_in(structures) & (pl.col("game_seconds") > 0))
    .group_by("ext_fs_id", "unit_type_name")
    .agg(pl.col("game_seconds").min())
    .collect()
    .pivot(on="unit_type_name", index="ext_fs_id", values="game_seconds")
    .lazy()
)
build = (
    games.lazy().select("ext_fs_id", "race", "result")
    .join(openings, on="ext_fs_id", how="left")
    .join(first_army, on="ext_fs_id", how="left")
    .join(structure_times, on="ext_fs_id", how="left")
    .collect()
)
build.group_by("race", "opening").agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate")) \
    .filter(pl.col("games") >= 5).sort("games", descending=True)
""")

code(r"""
(
    pl.collect_all([
        build.lazy().group_by("first_army_unit").agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"),
                                                     pl.col("first_army_seconds").median().round(0).alias("median_seconds"))
        .filter(pl.col("games") >= 10).sort("games", descending=True),
        build.lazy().group_by("most_made_unit").agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"))
        .filter(pl.col("games") >= 10).sort("games", descending=True),
    ])
)
""")

md(r"""
### Tech timings, wins against losses

The median time each tech structure was started in the wins and in the losses, and in how many
games it was built. A structure built in most wins and few losses, or earlier in the wins, is
worth a look.
""")

code(r"""
present = [name for name in structures if name in build.columns]
(
    build.lazy()
    .unpivot(index=["ext_fs_id", "result"], on=present, variable_name="structure", value_name="seconds")
    .group_by("structure", "result")
    .agg((pl.col("seconds").is_not_null().mean() * 100).round(0).alias("built_in_pct"),
         pl.col("seconds").median().round(0).alias("median_seconds"))
    .collect()
    .pivot(on="result", index="structure", values=["built_in_pct", "median_seconds"])
    .sort("structure")
)
""")

md(r"""
## Expansions

The townhalls started by the main player, and how many were alive at each minute: a townhall
counts from when it was started until it died.
""")

code(r"""
TOWNHALLS = ["Hatchery", "Lair", "Hive", "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Nexus"]
my_units = games.lazy().select("ext_fs_id", pl.col("player_id").alias("control_player_id"))
townhalls = (
    s2.scan(IPC_DIR, "unit_born")
    .filter(pl.col("ext_fs_id").is_in(game_ids) & pl.col("unit_type_name").is_in(["Hatchery", "CommandCenter", "Nexus"]))
    .join(my_units, on=["ext_fs_id", "control_player_id"], how="semi")
    .unique(["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], keep="first")
    .select("ext_fs_id", "unit_tag_index", "unit_tag_recycle", s2.game_seconds().alias("started"))
    .join(
        s2.scan(IPC_DIR, "unit_died").filter(pl.col("ext_fs_id").is_in(game_ids) & pl.col("unit_died_name").is_in(TOWNHALLS))
        .select("ext_fs_id", "unit_tag_index", "unit_tag_recycle", s2.game_seconds().alias("died")),
        on=["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], how="left",
    )
)
MINUTES = [4, 6, 8, 10, 12, 15]
bases = (
    townhalls.group_by("ext_fs_id")
    .agg(
        *[((pl.col("started") <= minute * 60) & (pl.col("died").is_null() | (pl.col("died") > minute * 60))).sum().alias(f"bases_{minute}")
          for minute in MINUTES],
        pl.col("started").filter(pl.col("started") > 0).sort().get(0, null_on_oob=True).alias("expansion_2"),
        pl.col("started").filter(pl.col("started") > 0).sort().get(1, null_on_oob=True).alias("expansion_3"),
        pl.col("started").filter(pl.col("started") > 0).sort().get(2, null_on_oob=True).alias("expansion_4"),
    )
    .join(won, on="ext_fs_id")
    .collect()
)
(
    bases.lazy()
    .group_by("bases_8")
    .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"))
    .sort("bases_8")
    .collect()
)
""")

code(r"""
expansions = bases.unpivot(index=["ext_fs_id", "result"], on=["expansion_2", "expansion_3", "expansion_4"],
                           variable_name="expansion", value_name="seconds").drop_nulls("seconds")
fig = px.box(expansions, x="expansion", y="seconds", color="result", template=TEMPLATE, color_discrete_map=RESULT_COLORS,
             title="When the 2nd, 3rd and 4th townhalls were started", points=False)
fig.show()
""")

md(r"""
## Economy and army, minute by minute

From the stats of the tracker events, sampled about every 7 seconds: the workers, the income and
the army value (minerals and vespene of the army alive) of the main player, and of both
computers together. The first sample after each minute is used.
""")

code(r"""
participants = (
    games.lazy().select("ext_fs_id", pl.col("player_id").alias("me"), "result")
)
per_player = (
    s2.scan(IPC_DIR, "stats")
    .filter(pl.col("ext_fs_id").is_in(game_ids))
    .with_columns(s2.game_seconds())
    .with_columns((pl.col("game_seconds") // 60).cast(pl.Int32).alias("minute"))
    .filter(pl.col("minute") <= 20)
    .join(participants, on="ext_fs_id")
    .with_columns(pl.when(pl.col("player_id") == pl.col("me")).then(pl.lit("me")).otherwise(pl.lit("computers")).alias("side"))
    .group_by("ext_fs_id", "result", "side", "player_id", "minute")
    .agg(
        pl.col("workers_active_count").sort_by("game_seconds").first().alias("workers"),
        (pl.col("minerals_collection_rate") + pl.col("vespene_collection_rate")).sort_by("game_seconds").first().alias("income"),
        (pl.col("minerals_used_current_army") + pl.col("vespene_used_current_army")).sort_by("game_seconds").first().alias("army"),
        (pl.col("minerals_lost_army") + pl.col("vespene_lost_army")).sort_by("game_seconds").first().alias("army_lost"),
    )
    .collect()
)
# Both computers together.
per_minute = (
    per_player.lazy()
    .group_by("ext_fs_id", "result", "side", "minute")
    .agg(pl.col("workers", "income", "army", "army_lost").sum())
    .collect()
)
medians = (
    per_minute.lazy()
    .group_by("result", "side", "minute")
    .agg(pl.col("workers", "income", "army").median())
    .with_columns(pl.concat_str("side", pl.lit(", "), "result").alias("series"))
    .sort("minute")
    .collect()
)
# Mine only, the computers cheat.
for measure in ["workers", "income", "army"]:
    fig = px.line(medians.filter(pl.col("side") == "me"), x="minute", y=measure, color="result", template=TEMPLATE,
                  color_discrete_map=RESULT_COLORS, title=f"My {measure}, median of the wins and of the losses", markers=True)
    fig.update_traces(line_width=2, marker_size=8)
    fig.show()
""")

md(r"""
### How much the computers cheat

Measured, not assumed, per phase of the games that lasted until the end of the phase, each
player apart:

- **spent per minute**: the minerals and vespene of everything the player has alive or lost
  (army, economy, technology), from the start to the end of the phase, per minute. It counts the
  resources the computers get without mining them.
- **collection rate per worker**: the income the game reports, divided by the active workers.

The multiplier is the median of a computer divided by the median of the main player, both
computers together are twice that. The resources a computer keeps unspent are not counted.
""")

code(r"""
SPENT = [f"{resource}_{kind}_{category}" for resource in ["minerals", "vespene"] for kind in ["used_current", "lost"]
         for category in ["army", "economy", "technology"]]
PHASES = [(4, 8), (8, 12), (12, 20), (20, 40), (40, 80)]
bounds = sorted({minute for phase in PHASES for minute in phase})
samples = (
    s2.scan(IPC_DIR, "stats")
    .filter(pl.col("ext_fs_id").is_in(game_ids))
    .with_columns(s2.game_seconds())
    .with_columns((pl.col("game_seconds") // 60).cast(pl.Int32).alias("minute"))
    .filter(pl.col("minute").is_in(bounds))
    .join(participants.select("ext_fs_id", "me"), on="ext_fs_id")
    .with_columns(pl.when(pl.col("player_id") == pl.col("me")).then(pl.lit("me")).otherwise(pl.lit("computer")).alias("side"),
                  pl.sum_horizontal(SPENT).alias("spent"),
                  (pl.col("minerals_collection_rate") + pl.col("vespene_collection_rate")).alias("rate"))
    .group_by("ext_fs_id", "player_id", "side", "minute")
    .agg(pl.col("spent", "rate", "workers_active_count").sort_by("game_seconds").first())
    .collect()
)
phases = pl.concat([
    samples.filter(pl.col("minute") == start).join(
        samples.filter(pl.col("minute") == end), on=["ext_fs_id", "player_id", "side"], suffix="_end"
    ).select(
        pl.lit(f"{start:02}:00-{end:02}:00").alias("phase"), "side",
        ((pl.col("spent_end") - pl.col("spent")) / (end - start)).alias("spent_per_minute"),
        (((pl.col("rate") + pl.col("rate_end")) / 2) / ((pl.col("workers_active_count") + pl.col("workers_active_count_end")) / 2).clip(lower_bound=1))
        .alias("rate_per_worker"),
        ((pl.col("workers_active_count") + pl.col("workers_active_count_end")) / 2).alias("workers"),
    )
    for start, end in PHASES
])
cheat = (
    phases.lazy()
    .group_by("phase", "side")
    .agg(pl.len().alias("players"), pl.col("spent_per_minute", "rate_per_worker", "workers").median())
    .collect()
    .pivot(on="side", index="phase", values=["players", "spent_per_minute", "rate_per_worker", "workers"])
    .with_columns(
        (pl.col("spent_per_minute_computer") / pl.col("spent_per_minute_me")).round(2).alias("spent_multiplier"),
        (pl.col("rate_per_worker_computer") / pl.col("rate_per_worker_me")).round(2).alias("rate_per_worker_multiplier"),
    )
    .sort("phase")
)
fig = px.bar(phases.group_by("phase", "side").agg(pl.col("spent_per_minute").median()).sort("phase"), x="phase",
             y="spent_per_minute", color="side", barmode="group", template=TEMPLATE, color_discrete_sequence=SERIES_COLORS,
             title="Resources spent per minute, median, me and each computer")
fig.show()
cheat.with_columns(pl.col(pl.Float64).round(1))
""")

md(r"""
### The army against both computers

The army value of the main player divided by the army value of both computers, at each minute.
It is what the main player faces, not a target: with their extra income the computers rebuild
faster than any human could, the wins show the ratio that was enough to hold.
""")

code(r"""
ratio = (
    per_minute.lazy()
    .collect()
    .pivot(on="side", index=["ext_fs_id", "result", "minute"], values="army")
    .lazy()
    .with_columns((pl.col("me") / pl.col("computers").clip(lower_bound=1)).alias("army_ratio"))
    .group_by("result", "minute")
    .agg(pl.col("army_ratio").median())
    .sort("minute")
    .collect()
)
fig = px.line(ratio, x="minute", y="army_ratio", color="result", template=TEMPLATE, color_discrete_map=RESULT_COLORS,
              markers=True, title="My army / the army of both computers, median")
fig.update_traces(line_width=2, marker_size=8)
fig.show()
""")

md(r"""
## Actions

The commands of the main player, from the three cmd files, a command once (see `s2.casts`), and the
abilities that need attention: Inject Larva, Creep Tumors and Transfuse. They are counted in the
first 10 minutes of the games that reached 10:00, so that the long games do not count more and
the games left early do not count less.
""")

code(r"""
my_names = games.lazy().select("ext_fs_id", "player_name")
my_casts = (
    s2.casts(IPC_DIR)
    .filter(pl.col("ext_fs_id").is_in(game_ids))
    .join(my_names, on=["ext_fs_id", "player_name"], how="semi")
    .with_columns(s2.game_seconds())
)
MACRO_ABILITIES = {"SpawnLarva.Execute": "injects", "Build.CreepTumorQueen": "queen_tumors",
                   "Build.CreepTumor": "tumor_spreads", "Transfusion.Execute": "transfuses"}
actions = (
    my_casts.filter(pl.col("ext_fs_id").is_in(full_ids) & (pl.col("game_seconds") <= FULL_GAME_SECONDS))
    .group_by("ext_fs_id")
    .agg(
        pl.len().alias("commands_first_10"),
        *[(pl.col("ability") == ability).sum().alias(f"{name}_first_10") for ability, name in MACRO_ABILITIES.items()],
    )
    .join(won, on="ext_fs_id")
    .collect()
)
first_10 = ["commands_first_10", *[f"{name}_first_10" for name in MACRO_ABILITIES.values()]]
actions.group_by("result").agg(pl.len().alias("games"), pl.col(first_10).median().round(1))
""")

md(r"""
## Where the losses happen

At what minute, from 6:00, the army value of the main player first drops below half of its
usual army at that minute (the median of the wins), in the wins and in the losses, and the computer units that killed the most units of
the main player in each.
""")

code(r"""
# The reference is the usual army of the wins at the same minute, not the cheating computers.
win_army = (
    per_minute.lazy().filter((pl.col("side") == "me") & (pl.col("result") == "Win"))
    .group_by("minute").agg(pl.col("army").median().alias("win_median_army"))
)
behind = (
    per_minute.lazy()
    .filter(pl.col("side") == "me")
    .join(win_army, on="minute")
    .filter((pl.col("minute") >= 6) & (pl.col("army") < 0.5 * pl.col("win_median_army")))
    .group_by("ext_fs_id", "result")
    .agg(pl.col("minute").min().alias("first_minute_behind"))
    .collect()
)
fig = px.histogram(behind, x="first_minute_behind", color="result", barmode="group", template=TEMPLATE,
                   color_discrete_map=RESULT_COLORS, title="First minute with less than half the usual army of the wins")
fig.show()
behind.group_by("result").agg(pl.len().alias("games_behind_at_some_point"), pl.col("first_minute_behind").median())
""")

code(r"""
my_unit_tags = (
    s2.scan(IPC_DIR, "unit_born")
    .filter(pl.col("ext_fs_id").is_in(game_ids))
    .join(my_units, on=["ext_fs_id", "control_player_id"], how="semi")
    .select("ext_fs_id", "unit_tag_index", "unit_tag_recycle")
    .unique()
)
killed_by = (
    s2.scan(IPC_DIR, "unit_died")
    .filter(pl.col("ext_fs_id").is_in(game_ids) & pl.col("unit_killer_name").is_not_null())
    .join(my_unit_tags, on=["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], how="semi")
    .join(games.lazy().select("ext_fs_id", "player_id", "result"), on="ext_fs_id")
    .filter(pl.col("killer_player_id") != pl.col("player_id"))
    .filter(~pl.col("unit_died_name").is_in(["Larva", "Egg", "Broodling", "CreepTumorBurrowed", "Changeling"]))
    .group_by("result", "unit_killer_name")
    .agg(pl.len().alias("my_units_killed"))
    .with_columns((pl.col("my_units_killed") / pl.col("my_units_killed").sum().over("result") * 100).round(1).alias("pct_of_my_losses"))
    .collect()
    .pivot(on="result", index="unit_killer_name", values="pct_of_my_losses")
    .with_columns((pl.col("Loss") - pl.col("Win")).round(1).alias("more_in_losses"))
    .sort("more_in_losses", descending=True, nulls_last=True)
)
killed_by.head(15)
""")

md(r"""
## What seems to work

Every measure of a game that reached 10:00, split in four equal groups of games from its lowest
to its highest value (quartiles), with the win rate of each group. A timing in seconds is better
low, a count is better high. The measures whose win rate changes the most
from the lowest to the highest group tell what goes with winning: the workers, the army and the
bases at fixed minutes, the timings of the opening and the actions.
""")

code(r"""
army_at = per_minute.filter(pl.col("side") == "me").pivot(on="minute", index="ext_fs_id", values=["workers", "army", "income"])
keep_minutes = [f"{measure}_{minute}" for measure in ["workers", "army", "income"] for minute in [4, 6, 8, 10]]
features = (
    games.lazy().filter(pl.col("ext_fs_id").is_in(full_ids)).select("ext_fs_id", "result")
    .join(build.lazy().select("ext_fs_id", "first_army_seconds", *[name for name in ["SpawningPool", "Extractor", "Lair", "RoachWarren", "EvolutionChamber"] if name in build.columns]), on="ext_fs_id", how="left")
    .join(bases.lazy().select("ext_fs_id", "expansion_2", "expansion_3", "expansion_4", "bases_6", "bases_8", "bases_10"), on="ext_fs_id", how="left")
    .join(actions.lazy().select("ext_fs_id", *first_10), on="ext_fs_id", how="left")
    .join(army_at.lazy().select("ext_fs_id", *[name for name in keep_minutes if name in army_at.columns]), on="ext_fs_id", how="left")
    .collect()
)
measures = [name for name in features.columns if name not in ("ext_fs_id", "result")]
quartiles = pl.concat(
    [
        features.lazy()
        .filter(pl.col(measure).is_not_null())
        .with_columns(pl.col(measure).qcut(4, labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"], allow_duplicates=True).alias("quartile"))
        .group_by("quartile")
        .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().alias("win_rate"), pl.col(measure).median().alias("median"))
        .with_columns(pl.lit(measure).alias("measure"))
        for measure in measures
    ],
    how="vertical_relaxed",
).collect()
effect = (
    quartiles.pivot(on="quartile", index="measure", values="win_rate")
    .select("measure", "Q1 lowest", "Q2", "Q3", "Q4 highest")
    .with_columns((pl.col("Q4 highest") - pl.col("Q1 lowest")).alias("highest_minus_lowest"))
    .sort(pl.col("highest_minus_lowest").abs(), descending=True)
)
effect.with_columns(pl.exclude("measure").round(3))
""")

code(r"""
top = effect.head(6)["measure"].to_list()
fig = px.bar(quartiles.filter(pl.col("measure").is_in(top)).sort("quartile"), x="quartile", y="win_rate", facet_col="measure",
             facet_col_wrap=3, hover_data=["games", "median"], template=TEMPLATE, color_discrete_sequence=SERIES_COLORS,
             title="Win rate by quartile of the measures that change it the most")
fig.update_yaxes(tickformat=".0%", range=[0, 1])
fig.for_each_annotation(lambda annotation: annotation.update(text=annotation.text.split("=")[-1]))
fig.show()
""")

md(r"""
## The random seed of the game

Every game has a random seed (`lobby_random_seed`), the computers decide with it among the
choices of their build, so it may explain why the same build plays differently. It can only be
seen through what the computers do: if the seed mattered for the result, the win rate would
change between groups of seeds, and the same seed would give the same openings of the
computers. The first army unit and the first expansion of each computer are their opening.
""")

code(r"""
seed_groups = (
    games.lazy()
    .with_columns(pl.col("lobby_random_seed").qcut(10, allow_duplicates=True).alias("seed_decile"))
    .group_by("seed_decile")
    .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"),
         pl.col("lobby_random_seed").min().alias("from_seed"))
    .sort("from_seed")
    .collect()
)
print(f"{games['lobby_random_seed'].n_unique()} different seeds in {games.height} games")
# With about 150 games per group, the win rate of a group varies by about 4 points by chance.
win_rate = games["result"].eq("Win").mean()
print(f"Standard error of a group: {(win_rate * (1 - win_rate) / (games.height / 10)) ** 0.5:.3f}")
seed_groups
""")

code(r"""
ai_born = (
    s2.scan(IPC_DIR, "unit_born")
    .filter(pl.col("ext_fs_id").is_in(game_ids) & (pl.col("ext_replay_loop") > 0) & pl.col("control_player_id").is_in([1, 2, 3, 4]))
    .join(games.lazy().select("ext_fs_id", "player_id"), on="ext_fs_id")
    .filter(pl.col("control_player_id") != pl.col("player_id"))
    .unique(["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], keep="first")
    .select("ext_fs_id", "control_player_id", "unit_type_name", "creator_ability_name", s2.game_seconds())
)
# The units are trained, the townhalls are started without a creator ability.
ai_units = ai_born.filter(pl.col("creator_ability_name").is_not_null())
ai_openings = (
    ai_units.filter(is_unit())
    .sort("game_seconds")
    .group_by("ext_fs_id", "control_player_id")
    .agg(pl.col("unit_type_name").first().alias("ai_first_army_unit"), pl.col("game_seconds").first().round(0).alias("ai_first_army_seconds"))
    .join(
        ai_born.filter(pl.col("unit_type_name").is_in(["CommandCenter", "Nexus", "Hatchery"]))
        .group_by("ext_fs_id", "control_player_id").agg(pl.col("game_seconds").min().round(0).alias("ai_expansion_seconds")),
        on=["ext_fs_id", "control_player_id"], how="left",
    )
    .join(won, on="ext_fs_id")
    .collect()
)
(
    ai_openings.lazy()
    .group_by("ai_first_army_unit")
    .agg(pl.len().alias("computers"), (pl.col("result") == "Win").mean().round(3).alias("my_win_rate"),
         pl.col("ai_first_army_seconds").median(), pl.col("ai_expansion_seconds").median())
    .filter(pl.col("computers") >= 10)
    .sort("computers", descending=True)
    .collect()
)
""")

md(r"""
### Early or late expansions of the computers

The Economic Focus computers expand early; when one of them did not, it attacked instead. The win
rate by when the computers took their first expansion, the earliest of the two.
""")

code(r"""
(
    ai_openings.lazy()
    .group_by("ext_fs_id", "result")
    .agg(pl.col("ai_expansion_seconds").min().alias("first_ai_expansion"), pl.col("ai_first_army_seconds").min().alias("first_ai_army"))
    .with_columns(pl.col("first_ai_expansion").cut([60, 90, 120, 180, 240]).alias("first_ai_expansion_seconds"))
    .group_by("first_ai_expansion_seconds")
    .agg(pl.len().alias("games"), (pl.col("result") == "Win").mean().round(3).alias("win_rate"), pl.col("first_ai_army").median())
    .sort("first_ai_expansion_seconds")
    .collect()
)
""")

md(r"""
## The best and the worst games

The wins with the most army against both computers at 10:00 and the losses with the least, to
open in swarmy (Replay Detail, by the file) and watch.
""")

code(r"""
at_10 = (
    per_minute.filter(pl.col("minute") == 10)
    .pivot(on="side", index=["ext_fs_id", "result"], values="army")
    .with_columns((pl.col("me") / pl.col("computers").clip(lower_bound=1)).round(2).alias("army_ratio_10"))
    .join(games.select("ext_fs_id", "title", "ext_datetime", (pl.col("duration") / 60).round(1).alias("minutes"), "file"), on="ext_fs_id")
)
display(at_10.filter(pl.col("result") == "Win").sort("army_ratio_10", descending=True).head(5))
at_10.filter(pl.col("result") == "Loss").sort("army_ratio_10").head(5)
""")

nb = nbf.v4.new_notebook()
nb.cells = cells
nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
nbf.write(nb, "Vs_Cheater_AI.ipynb")
print("Wrote Vs_Cheater_AI.ipynb")
