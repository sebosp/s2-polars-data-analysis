# s2-polars-data-analysis 3.6.0
Starcraft 2 - Polars - Data Analysis Jupyter Notebooks

Example generated reports using the Basic-Unit-Queries
- [Latest Replay Unit Born including creator ability in Map](https://sebosp.github.io/s2-polars-data-analysis/jupyter_notebooks/static/latest_map_unit_born.html)
- [Latest Replay Map Unit Died in Map](https://sebosp.github.io/s2-polars-data-analysis/jupyter_notebooks/static/latest_map_unit_died.html)
- [Latest Replay Unit Killer to Unit Died Frequency](https://sebosp.github.io/s2-polars-data-analysis/jupyter_notebooks/static/latest_map_unit_killer_to_died_freq.html)

## Compat
The releases in this repo major version are compatible with the s2protocol-rs major versions.

3.6.0 reads the snapshot of s2protocol-rs 3.6.0, partitioned by the day the games were played
(`ipcs/year=YYYY/month=MM/day=DD/<file>.arrow`) and keyed by `ext_fs_id`. Older snapshots (`.ipc`
files, `ext_fs_replay_sha256`) must be generated again, i.e. with swarmy's Optimize.

## The snapshot

`jupyter_notebooks/snapshot.py` reads it, the notebooks import it:

```python
import snapshot as s2

details = s2.scan(ipc_dir, "details")       # every day as one LazyFrame
players = s2.players(ipc_dir)               # each player of each game with its tracker player_id
games = s2.one_vs_one(ipc_dir)              # the 1v1 games with the matchup, i.e. PvT
s2.game_seconds()                           # the game time from ext_replay_loop
```

The tracker events (stats, upgrades, unit_born, unit_died) identify the player by `player_id`, the
details by name, `players()` maps one to the other through unit_born. The races of the details are
localized, `race` is `T`, `Z`, `P` or `?`.

### Jupyter Notebooks

```
$ uv sync
$ uv run jupyter lab --ip 0.0.0.0
```

Then open your browser and locate the Notebbooks, for example:

[Basic UnitBorn Queries](./jupyter_notebooks/Basic-Unit-Queries.ipynb)

[functime examples](./jupyter_notebooks/functime.ipynb): forecasting the race balance per week,
cross-validation, the trend of the upgrade timings, a global model of the workers per minute across
games and the features of the army curves of the winners and the losers.
![All units born](https://github.com/sebosp/s2protocol-rs/assets/873436/2307780a-bc62-4cd4-9daf-a3e622bdb5b7)
![Most effective units across all games](https://github.com/sebosp/s2protocol-rs/assets/873436/cba9da20-a034-47f3-9016-bfd6db21247b)

