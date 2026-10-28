"""Downloads the replays of the AI Arena results (https://aiarena.net/api/results/), newest first,
to ~/SC2Replays/aiarena_net/<year>/<month>/<day>/, politely:

- One API request at a time, at least 5 seconds apart (the Crawl-delay of aiarena.net), with the
  API token of ~/.config/aiarena/token (https://aiarena.net/profile/token/).
- The replays are downloaded one at a time from the storage of AI Arena (S3), without the token,
  as the AI Arena wiki asks.
- What is downloaded is kept in manifest.sqlite next to the replays, a stopped run continues where
  it was and the replays already downloaded are not downloaded again.
- It stops once the replays add up to --max-gb (50 GB by default).

    python -I scripts/aiarena_download.py [--max-gb 50] [--page-size 1000]
"""

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://aiarena.net/api/results/"
USER_AGENT = "swarmy-replay-archiver (kraige@gmail.com)"
API_DELAY_SECONDS = 5
DOWNLOAD_DELAY_SECONDS = 0.5
RETRIES = 5


def log(message: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def open_manifest(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(root / "manifest.sqlite")
    db.execute(
        """CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY, match INTEGER, created TEXT, bot1 TEXT, bot2 TEXT,
            type TEXT, game_steps INTEGER, path TEXT, bytes INTEGER, status TEXT, error TEXT)"""
    )
    db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
    db.commit()
    return db


def state(db: sqlite3.Connection, key: str, default: str) -> str:
    row = db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_state(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, value))
    db.commit()


def request(url: str, token: str | None = None, timeout: int = 120) -> bytes:
    """GET with retries, waiting longer after each failure and when asked to slow down."""
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Token {token}"
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            if err.code in (401, 403, 404):
                raise
            wait = int(err.headers.get("Retry-After", 0) or 0) or 30 * (attempt + 1)
            log(f"HTTP {err.code} for {url.split('?')[0]}, retrying in {wait}s")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            wait = 30 * (attempt + 1)
            log(f"{err} for {url.split('?')[0]}, retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Giving up on {url.split('?')[0]}")


def replay_path(root: Path, result: dict) -> Path:
    created = datetime.fromisoformat(result["created"].replace("Z", "+00:00"))
    name = Path(urllib.parse.urlparse(result["replay_file"]).path).name
    return root / f"{created:%Y}" / f"{created:%m}" / f"{created:%d}" / f"{result['id']}_{name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/SC2Replays/aiarena_net")
    parser.add_argument("--token-file", default="~/.config/aiarena/token")
    parser.add_argument("--max-gb", type=float, default=50)
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    token = Path(args.token_file).expanduser().read_text().strip()
    db = open_manifest(root)
    max_bytes = int(args.max_gb * 1e9)

    # Newest first. New results are added at the top while this runs, so the offset only moves
    # forward and the results seen again are skipped by their id.
    offset = int(state(db, "offset", "0"))
    last_api_request = 0.0
    while True:
        total = db.execute("SELECT COALESCE(SUM(bytes), 0) FROM results WHERE status = 'ok'").fetchone()[0]
        if total >= max_bytes:
            log(f"Reached {total / 1e9:.1f} GB, stopping")
            break
        time.sleep(max(0.0, last_api_request + API_DELAY_SECONDS - time.time()))
        url = f"{API}?{urllib.parse.urlencode({'limit': args.page_size, 'offset': offset, 'ordering': '-id'})}"
        page = json.loads(request(url, token, timeout=300))
        last_api_request = time.time()
        results = page.get("results", [])
        log(f"Offset {offset} of {page.get('count')}: {len(results)} results, {total / 1e9:.2f} GB so far")
        if not results:
            break
        known = {row[0] for row in db.execute(
            f"SELECT id FROM results WHERE id IN ({','.join('?' * len(results))})", [r["id"] for r in results]
        )}
        downloaded = 0
        for result in results:
            if result["id"] in known:
                continue
            row = (result["id"], result.get("match"), result.get("created"), result.get("bot1_name"),
                   result.get("bot2_name"), result.get("type"), result.get("game_steps"))
            if not result.get("replay_file") or result.get("replay_file_has_been_cleaned"):
                db.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,NULL,0,'no_replay',NULL)", row)
                continue
            path = replay_path(root, result)
            try:
                data = request(result["replay_file"])
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.rename(path)
                db.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,'ok',NULL)",
                           (*row, str(path.relative_to(root)), len(data)))
                downloaded += 1
                total += len(data)
            except Exception as err:  # Kept as failed in the manifest, i.e. an expired signed link.
                db.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,0,'failed',?)",
                           (*row, str(path.relative_to(root)), str(err)))
            db.commit()
            if total >= max_bytes:
                break
            time.sleep(DOWNLOAD_DELAY_SECONDS)
        else:
            # Only a page done to the end moves the offset, the next run continues the page.
            offset += len(results)
            set_state(db, "offset", str(offset))
        log(f"Downloaded {downloaded} replays of the page, {total / 1e9:.2f} GB")
        if not page.get("next"):
            break


if __name__ == "__main__":
    main()
