"""The charts of the notebooks: one palette, one template, PNG + HTML export.

The colors follow the entity, never its rank: a race or a result keeps its color in every
chart of every notebook. Protoss, Terran and Zerg take the first three categorical slots
(blue, orange, aqua: they stay apart for the color blind), the wins are blue and the losses
orange.

    import viz
    fig = px.line(df, x="minute", y="workers", color="race", color_discrete_map=viz.RACE_COLORS, **viz.LINE)
    viz.show(fig, "level_2_workers_by_race")   # shows it and writes static/img/<name>.png + .html
"""

import os
import warnings
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go

# The categorical palette, in order: blue, orange, aqua, yellow, magenta, green, violet, red.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
RACE_COLORS = {"P": SERIES[0], "T": SERIES[1], "Z": SERIES[2], "?": "#898781"}
RESULT_COLORS = {"Win": SERIES[0], "Loss": SERIES[1]}
# The de-emphasis gray, for the context series behind the one that matters.
MUTED = "#c3c2b7"
# One hue, light to dark, for magnitudes (heatmaps).
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
# Two hues and a neutral gray in the middle, for values around a center (a win rate around 50%).
DIVERGING = ["#1c5cab", "#86b6ef", "#f0efec", "#f1a07f", "#d03b3b"]
TEMPLATE = "plotly_white"
WIDTH, HEIGHT = 1000, 450

# Keyword arguments for plotly express, the same chrome everywhere.
LINE = dict(template=TEMPLATE, width=WIDTH, height=HEIGHT, color_discrete_sequence=SERIES)
BAR = dict(template=TEMPLATE, width=WIDTH, height=HEIGHT, color_discrete_sequence=SERIES)

# Where `show()` writes the figures, relative to the notebook directory.
IMG_DIR = Path(__file__).parent / "static" / "img"

px.defaults.template = TEMPLATE
px.defaults.color_discrete_sequence = SERIES
px.defaults.width = WIDTH
px.defaults.height = HEIGHT


def style(fig: go.Figure) -> go.Figure:
    """Thin marks, hairline grid, the legend on top: the same look for every chart."""
    # The default marks, a trace that sets its own marker size keeps it.
    fig.for_each_trace(lambda trace: trace.update(line_width=2, marker_size=8) if trace.type == "scatter" and trace.marker.size is None else None)
    fig.update_layout(
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
        margin=dict(l=60, r=30, t=70, b=50),
        plot_bgcolor="#fcfcfb",
        paper_bgcolor="#fcfcfb",
    )
    fig.update_xaxes(gridcolor="#e1e0d9", zerolinecolor="#c3c2b7", linecolor="#c3c2b7")
    fig.update_yaxes(gridcolor="#e1e0d9", zerolinecolor="#c3c2b7", linecolor="#c3c2b7")
    # The facet titles sit at the top of the panels: the legend goes above them, the title above the legend.
    if any(annotation.yref == "paper" and (annotation.y or 0) >= 1 for annotation in fig.layout.annotations):
        fig.update_layout(legend=dict(y=1.07), margin=dict(t=110), title=dict(y=0.98, yanchor="top"))
    return fig


def show(fig: go.Figure, name: str | None = None, scale: int = 2) -> None:
    """Shows the figure and, with a name, writes `static/img/<name>.png` (and `.html`).

    The PNG needs kaleido and a Chrome, `uv run plotly_get_chrome`; without them only the HTML
    is written and a warning tells why. `S2_NO_FIGURE_FILES=1` skips the files.
    """
    style(fig)
    fig.show()
    if name is None or os.environ.get("S2_NO_FIGURE_FILES"):
        return
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    fig.write_html(IMG_DIR / f"{name}.html", include_plotlyjs="cdn")
    try:
        fig.write_image(IMG_DIR / f"{name}.png", scale=scale)
    except Exception as error:  # kaleido or Chrome missing
        warnings.warn(f"{name}.png not written, install kaleido and run `uv run plotly_get_chrome`: {error}")
