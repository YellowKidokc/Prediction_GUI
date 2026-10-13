"""Chrome history adapter — YouTube watches straight from the browser's own
History SQLite. No extension, no Google account, no resident process.
Run it at shutdown (or whenever); it only reads.

Chrome locks the live file, so we copy it first. Subject = video id,
context = {channel? (unknown from history alone), title, url, hour, dow}.
Channel is filled later by the yt worker; the harness keys on 'subject' until then.

    python -m harness.adapters.chrome_history            (default profile)
    python -m harness.adapters.chrome_history "C:\\...\\Profile 2\\History"
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from harness.contract import Event

DEFAULT = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default" / "History"
VIDEO_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")


def _chrome_time(us: int) -> str:
    # Chrome stores microseconds since 1601-01-01
    base = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
    return (base + dt.timedelta(microseconds=us)).isoformat(timespec="seconds")


def read(history_path: str | Path = DEFAULT, since_days: int | None = None) -> list[Event]:
    src = Path(history_path)
    if not src.exists():
        raise FileNotFoundError(f"Chrome History not found: {src}")
    tmp = Path(tempfile.mkdtemp()) / "History"
    shutil.copy2(src, tmp)                      # Chrome holds a lock on the original
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON u.id = v.url "
           "WHERE u.url LIKE '%youtube.com/watch%' OR u.url LIKE '%youtu.be/%' OR u.url LIKE '%youtube.com/shorts/%'")
    if since_days:
        cutoff = int((dt.datetime.now(dt.timezone.utc) - dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
                      - dt.timedelta(days=since_days)).total_seconds() * 1_000_000)
        sql += f" AND v.visit_time > {cutoff}"
    sql += " ORDER BY v.visit_time ASC"
    out = []
    for r in conn.execute(sql):
        m = VIDEO_RE.search(r["url"])
        if not m:
            continue
        ts = _chrome_time(int(r["visit_time"]))
        when = dt.datetime.fromisoformat(ts)
        out.append(Event(subject=m.group(1), action="watch", source="chrome_history", timestamp=ts,
                         id=f"yt_{m.group(1)}_{int(r['visit_time'])}",
                         context={"title": (r["title"] or "")[:200], "url": r["url"][:300],
                                  "hour": when.hour, "dow": when.weekday()}))
    conn.close()
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.runner import Runner
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    evs = read(path)
    print(f"found {len(evs)} YouTube visits; ingested {Runner(context_keys=('subject',)).ingest(evs)} new")
