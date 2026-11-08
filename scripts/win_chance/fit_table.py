"""The coefficients per 2 minutes of game, and the calibration of the interpolated model on
games left out (grouped by game)."""
import sys
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

cols = ["army", "income", "workers", "trade"]
df = pl.read_parquet(sys.argv[1]).with_columns(test=(pl.col("ext_fs_id").hash(7) % 5) == 0)
train, test = df.filter(~pl.col("test")), df.filter(pl.col("test"))
starts = list(range(2, 26, 2))
table = []
for lo in starts:
    hi = lo + 2 if lo < 24 else 999
    part = train.filter((pl.col("minute") >= lo) & (pl.col("minute") < hi))
    model = LogisticRegression(fit_intercept=False, C=10).fit(part.select(cols).to_numpy(), part["p1_won"].to_numpy())
    table.append((lo + 1, model.coef_[0], len(part)))
    print(f"minute {lo + 1:>2}: coef={np.round(model.coef_[0], 3).tolist()} n={len(part)}")
mids = np.array([m for m, _, _ in table], dtype=float)
coefs = np.array([c for _, c, _ in table])
def interp(minute):
    return np.array([np.interp(minute, mids, coefs[:, k]) for k in range(len(cols))]).T
X = test.select(cols).to_numpy()
p = 1 / (1 + np.exp(-(X * interp(test["minute"].to_numpy())).sum(axis=1)))
y = test["p1_won"].to_numpy()
print("held-out logloss", round(log_loss(y, p), 4), "accuracy", round(((p > .5) == y).mean(), 4))
bins = np.linspace(0, 1, 11)
idx = np.digitize(p, bins) - 1
for b in range(10):
    m = idx == b
    if m.sum():
        print(f"  predicted {bins[b]:.1f}-{bins[b+1]:.1f}: n={m.sum():>6} mean predicted={p[m].mean():.3f} actual={y[m].mean():.3f}")
print("RUST", [(int(m), [round(float(x), 3) for x in c]) for m, c, _ in table])
