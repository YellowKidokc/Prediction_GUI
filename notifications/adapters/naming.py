"""FIS/Coco/generic naming plans -> one editable approval batch.

CSV columns: current_path,proposed_name,confidence,reason
JSON: a list of objects with the same keys.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from notifications.contract import NotificationItem, NotificationTemplate


def read(path: str | Path) -> list[NotificationItem]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    items = []
    for row in rows:
        current = str(row.get("current_path") or row.get("current_name") or "").strip()
        proposed = str(row.get("proposed_name") or row.get("proposal") or "").strip()
        if not current or not proposed:
            continue
        raw_confidence = row.get("confidence")
        try: confidence = float(raw_confidence) if raw_confidence not in (None, "") else None
        except (TypeError, ValueError): confidence = None
        items.append(NotificationItem(
            subject=current,
            proposed_action=proposed,
            summary=str(row.get("reason") or "Naming proposal"),
            payload={"current_value": current, "confidence": confidence,
                     "risk_class": "mutation", "auto_approvable": False,
                     "source_record": row}))
    return items


def submit(engine, path: str | Path, desktop: bool = True) -> str:
    items = read(path)
    if not items:
        raise ValueError(f"no valid naming rows in {path}")
    return engine.submit(
        NotificationTemplate.APPROVAL_BATCH,
        f"Naming plan ready: {Path(path).name}",
        "Simulation only. Edit Final value, check rows, then approve/hold/reject.",
        f"naming:{Path(path).resolve()}", items, desktop=desktop)
