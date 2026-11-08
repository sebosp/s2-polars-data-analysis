# Win chance model of swarmy

The coefficients of `swarmy/src-tauri/src/replay_detail/win_chance.rs`, fitted on the 1v1 games
of a snapshot (27,441 games of the corvid-zt snapshot on 2026-10-29):

    python -I features.py <snapshot> features.parquet        # every 30 s from 02:00
    python -I counters.py <snapshot> <BalanceData json dir> features.parquet counters.parquet
    python -I fit.py counters.parquet army+income+workers+trade +counter   # per phase, CV by game
    python -I fit_table.py features.parquet                  # per 2 minutes, calibration, RUST table

`counters.py` adds how the alive armies counter each other (balance data strengths and
weaknesses), it did not improve the log loss on the full snapshot and is not in the model.
