"""CSV adapter — the universal way in.

Any CSV with columns  subject, action  becomes events. Every other column lands
in context. Optional: timestamp (ISO), source.

    python -m harness.adapters.csv_events path\to\file.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from harness.contract import Event


def read(path: str | Path, source: str = "csv") -> list[Event]:
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            subject = (row.pop("subject", "") or "").strip()
            action = (row.pop("action", "") or "event").strip()
            if not subject:
                continue
            ts = (row.pop("timestamp", "") or "").strip()
            src = (row.pop("source", "") or source).strip()
            ctx = {k: v for k, v in row.items() if v not in (None, "")}
            out.append(Event(subject=subject, action=action, context=ctx, source=src,
                             **({"timestamp": ts} if ts else {})))
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.runner import Runner
    evs = read(sys.argv[1])
    print(f"read {len(evs)} events; ingested {Runner().ingest(evs)} new")
