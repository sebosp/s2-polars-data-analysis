"""Checks of `jupyter_notebooks/snapshot.py` on a snapshot, `$S2_IPC_DIR` (see scripts/ci.sh)."""

import json
import os
import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jupyter_notebooks"))
import snapshot as s2  # noqa: E402

IPC_DIR = os.environ.get("S2_IPC_DIR")
pytestmark = pytest.mark.skipif(not IPC_DIR, reason="S2_IPC_DIR is not set")


@pytest.fixture(scope="module")
def con():
    return s2.duck(IPC_DIR, memory_limit="2GB")


def test_the_snapshot_is_of_a_compatible_s2protocol():
    metadata = json.loads((Path(IPC_DIR).expanduser() / "metadata.json").read_text())
    major, minor, _ = metadata["s2protocol_version"].split(".")
    assert (int(major), int(minor)) >= (5, 1), metadata["s2protocol_version"]


@pytest.mark.parametrize("name", [*s2.FILES, *s2.GAME_TABLES, "unit_init", "game_actions", "game_selections", "messages"])
def test_every_file_is_read(name):
    assert s2.scan(IPC_DIR, name).select(pl.len()).collect().item() > 0


def test_casts_have_the_three_cmd_files():
    targets = s2.casts(IPC_DIR).group_by("target").agg(pl.col("ability_name").unique()).collect()
    names = dict(zip(targets["target"], targets["ability_name"]))
    assert set(names) == {"point", "unit", "none"}
    # Trained units and Stimpack have no target, they were missing before 5.1 support.
    assert "Train" in names["none"]


def test_casts_are_the_same_in_polars_and_sql(con):
    columns = ["ext_fs_id", "user_id", "sequence", "ext_replay_loop", "ability", "target"]
    polars_casts = s2.casts(IPC_DIR).select(columns).collect()
    s2.same(polars_casts, con.sql(f"SELECT {', '.join(columns)} FROM casts"))


def test_games_have_one_winner(con):
    games = s2.games(IPC_DIR).collect()
    assert games.height > 0
    assert games["winner"].null_count() == 0
    s2.same(games.select("ext_fs_id").unique(), con.sql("SELECT DISTINCT ext_fs_id FROM games"))


def test_every_player_is_mapped_to_a_tracker_id():
    details = s2.scan(IPC_DIR, "details").filter(pl.col("player_observe") == 0).select("ext_fs_id").unique()
    players = s2.players(IPC_DIR).select("ext_fs_id").unique()
    assert details.join(players, on="ext_fs_id", how="anti").collect().height == 0
