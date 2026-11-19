"""Casebook: every solved stop is written down so the next one is free.

One JSON object per line in casebook.jsonl:
  {code, signature, why, fix_summary, edits:[{file, content}], solved_by, approved_by, ts}

Lookup order: exact signature first, then same code (offered to the models as
"learnings", even when they don't obviously match).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOK = HERE / "data" / "casebook.jsonl"
LEDGER = HERE / "data" / "ledger.jsonl"
HUMAN = HERE / "data" / "human_queue.jsonl"


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def all_cases() -> list[dict]:
    if not BOOK.exists():
        return []
    return [json.loads(l) for l in BOOK.read_text(encoding="utf-8").splitlines() if l.strip()]


def exact(signature: str) -> list[dict]:
    return [c for c in all_cases() if c.get("signature") == signature]


def learnings(code: str, limit: int = 8) -> list[dict]:
    """Same code first, then most recent others, summaries only."""
    cases = all_cases()
    same = [c for c in cases if c.get("code") == code]
    other = [c for c in cases if c.get("code") != code]
    pick = (same[::-1] + other[::-1])[:limit]
    return [{"code": c["code"], "why": c.get("why"), "fix": c.get("fix_summary")} for c in pick]


def record(stop: dict, fix_summary: str, edits: list[dict], solved_by: str, approved_by: str) -> None:
    _append(BOOK, {"code": stop["code"], "signature": stop["signature"], "why": stop["why"],
                   "fix_summary": fix_summary, "edits": edits,
                   "solved_by": solved_by, "approved_by": approved_by})


def ledger(event: str, **kw) -> None:
    _append(LEDGER, {"event": event, **kw})


def to_human(stop: dict, attempts: list[dict]) -> None:
    _append(HUMAN, {"stop": stop, "attempts": attempts})
