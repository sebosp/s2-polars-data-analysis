"""The screenshots of the DuckDB UI in the README, from a headless Chrome.

    S2_IPC_DIR=~/SC2Replays/ipcs uv run --with playwright python scripts/duckdb_ui_screenshots.py

Writes `jupyter_notebooks/static/img/duckdb_ui_<name>.png`. It uses the Chrome of
`uv run plotly_get_chrome` and a temporary DuckDB home, so your UI notebooks are not touched.
The UI loads its assets from ui.duckdb.org, it needs the network.
"""

import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from duckdb_ui import DEFAULT_DB, ROOT, build, s2  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CHROME = Path("~/.local/share/choreographer/deps/chrome-linux64/chrome").expanduser()
IMG_DIR = ROOT / "jupyter_notebooks" / "static" / "img"
SHOTS = {
    "examples": "SELECT level, name, query, title FROM examples ORDER BY level, name",
    "balance": "SELECT matchup, month::DATE AS month, games, round(win_rate, 3) AS win_rate FROM level_2.balance ORDER BY month DESC, matchup",
    "leaderboard": "SELECT * REPLACE (round(win_rate, 3) AS win_rate) FROM level_4.leaderboard",
    "map_balance": "SELECT title, matchup, games, round(first_race_win_rate, 3) AS first_race_win_rate FROM level_5.map_balance ORDER BY abs(edge) DESC",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as home:
        # The UI keeps its notebooks under $HOME, the temporary one keeps them apart from yours.
        os.environ["HOME"] = home
        con = build(s2.ipc_dir(), args.db)
        con.execute("INSTALL ui; LOAD ui;")
        print(con.execute("CALL start_ui_server()").fetchone()[0])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=2)
            for name, sql in SHOTS.items():
                run_in_new_notebook(page, sql, name)
            browser.close()
        con.execute("CALL stop_ui_server()")


def run_in_new_notebook(page, sql: str, name: str) -> None:
    """Runs the query alone in a new notebook and takes the screenshot."""
    page.goto("http://localhost:4213/notebooks", wait_until="networkidle", timeout=120000)
    page.wait_for_timeout(2000)
    # The welcome page on the first visit, the list of notebooks on the others.
    start = page.get_by_text(re.compile("EMPTY NOTEBOOK|BLANK NOTEBOOK", re.IGNORECASE))
    if start.count():
        start.first.click()
    else:
        page.get_by_role("button", name="Create", exact=True).click()
        page.wait_for_timeout(500)
        if not page.locator(".cm-content").count() and page.get_by_text("Add Cell").count() == 0:
            page.get_by_text(re.compile("notebook", re.IGNORECASE)).last.click()
    page.wait_for_timeout(2000)
    if not page.locator(".cm-content").count():
        page.get_by_text("Add Cell").last.click()
        page.wait_for_timeout(1000)
    page.locator(".cm-content").last.click()
    page.keyboard.type(sql)
    page.keyboard.press("Escape")  # closes the autocomplete
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(5000)
    page.mouse.click(1300, 860)  # the focus out of the editor
    page.wait_for_timeout(500)
    path = IMG_DIR / f"duckdb_ui_{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))
    print(path, os.path.getsize(path))


if __name__ == "__main__":
    main()
