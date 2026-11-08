"""Fits P(player 1 wins) = sigmoid(sum of coefficient * feature), without intercept so that the
two players are symmetric, per phase of the game, with cross validation grouped by game."""
import sys
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, accuracy_score
from sklearn.model_selection import GroupKFold

df = pl.read_parquet(sys.argv[1])
feature_sets = {k: v for k, v in {
    "army": ["army"],
    "army+income": ["army", "income"],
    "army+income+workers": ["army", "income", "workers"],
    "army+income+workers+trade": ["army", "income", "workers", "trade"],
    "+counter": ["army", "income", "workers", "trade", "counter"],
    "+counter_army": ["army", "income", "workers", "trade", "counter_army"],
}.items() if k in sys.argv[2:] or len(sys.argv) == 2}
phases = [(2, 6), (6, 10), (10, 15), (15, 20), (20, 99)]
y = df["p1_won"].to_numpy()
groups = df["ext_fs_id"].to_numpy()
for name, cols in feature_sets.items():
    print(f"== {name}")
    for lo, hi in phases:
        mask = ((df["minute"] >= lo) & (df["minute"] < hi)).to_numpy()
        X, yy, gg = df.filter(mask).select(cols).to_numpy(), y[mask], groups[mask]
        pred = np.zeros(len(yy))
        for train, test in GroupKFold(5).split(X, yy, gg):
            model = LogisticRegression(fit_intercept=False, C=10).fit(X[train], yy[train])
            pred[test] = model.predict_proba(X[test])[:, 1]
        model = LogisticRegression(fit_intercept=False, C=10).fit(X, yy)
        print(f"  {lo:>2}-{hi:<2} n={len(yy):>6} logloss={log_loss(yy, pred):.3f} acc={accuracy_score(yy, pred > .5):.3f} coef={np.round(model.coef_[0], 2).tolist()}")
