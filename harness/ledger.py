"""Ledger — one SQLite file. Events in, predictions out, outcomes scored.

Every engine's hit-rate is computed here, not by the engine. An engine never
grades its own homework.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contract import Event, Prediction, Candidate, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, action TEXT NOT NULL,
  context TEXT NOT NULL, source TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(timestamp);
CREATE TABLE IF NOT EXISTS predictions (
  id TEXT PRIMARY KEY, engine TEXT NOT NULL, target TEXT NOT NULL,
  context_key TEXT NOT NULL, top_value TEXT, top_conf REAL,
  candidates TEXT NOT NULL, markers TEXT NOT NULL, guidance TEXT,
  timestamp TEXT NOT NULL, outcome TEXT, was_correct INTEGER, resolved_at TEXT);
CREATE INDEX IF NOT EXISTS ix_pred_engine ON predictions(engine, resolved_at);
CREATE TABLE IF NOT EXISTS engines (
  name TEXT PRIMARY KEY, folder TEXT NOT NULL, kind TEXT NOT NULL,
  target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'shadow',
  registered_at TEXT NOT NULL, meta TEXT NOT NULL);
"""


class Ledger:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    # ---- events -------------------------------------------------------
    def add_event(self, e: Event) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
            (e.id, e.subject, e.action, json.dumps(e.context), e.source, e.timestamp))
        self.conn.commit()
        return cur.rowcount == 1

    def events(self, limit: int | None = None) -> list[Event]:
        sql = "SELECT * FROM events ORDER BY timestamp ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [Event(subject=r["subject"], action=r["action"], context=json.loads(r["context"]),
                      source=r["source"], timestamp=r["timestamp"], id=r["id"])
                for r in self.conn.execute(sql)]

    def event_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"])

    # ---- predictions --------------------------------------------------
    def add_prediction(self, p: Prediction) -> None:
        top = p.top
        self.conn.execute(
            "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
            (p.id, p.engine, p.target, p.context_key,
             top.value if top else None, top.confidence if top else None,
             json.dumps([c.__dict__ for c in p.candidates]), json.dumps(p.markers),
             p.guidance, p.timestamp))
        self.conn.commit()

    def resolve(self, context_key: str, target: str, outcome: str) -> int:
        """Score every unresolved prediction for this situation against what happened."""
        rows = self.conn.execute(
            "SELECT id, top_value FROM predictions WHERE context_key=? AND target=? AND resolved_at IS NULL",
            (context_key, target)).fetchall()
        for r in rows:
            # an abstention (no candidates) is closed but never scored, hit or miss
            correct = None if r["top_value"] is None else (1 if r["top_value"] == outcome else 0)
            self.conn.execute(
                "UPDATE predictions SET outcome=?, was_correct=?, resolved_at=? WHERE id=?",
                (outcome, correct, utc_now(), r["id"]))
        self.conn.commit()
        return len(rows)

    def open_predictions(self, limit: int = 200) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM predictions WHERE resolved_at IS NULL ORDER BY timestamp DESC LIMIT ?", (limit,))]

    # ---- scoreboard ---------------------------------------------------
    def scoreboard(self, last_n: int = 200) -> list[dict[str, Any]]:
        """Hit-rate per engine over its last N resolved predictions."""
        out = []
        for r in self.conn.execute("SELECT name, status, target FROM engines ORDER BY name"):
            rows = self.conn.execute(
                "SELECT was_correct FROM predictions WHERE engine=? AND resolved_at IS NOT NULL AND was_correct IS NOT NULL "
                "ORDER BY resolved_at DESC LIMIT ?", (r["name"], last_n)).fetchall()
            total = len(rows)
            hits = sum(1 for x in rows if x["was_correct"])
            pending = self.conn.execute(
                "SELECT COUNT(*) c FROM predictions WHERE engine=? AND resolved_at IS NULL",
                (r["name"],)).fetchone()["c"]
            out.append({"engine": r["name"], "status": r["status"], "target": r["target"],
                        "scored": total, "hits": hits,
                        "hit_rate": round(hits / total, 3) if total else None,
                        "pending": int(pending)})
        return out

    # ---- engine registry ---------------------------------------------
    def register_engine(self, name: str, folder: str, kind: str, target: str, meta: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO engines(name,folder,kind,target,status,registered_at,meta) VALUES (?,?,?,?,'shadow',?,?) "
            "ON CONFLICT(name) DO UPDATE SET folder=excluded.folder, kind=excluded.kind, "
            "target=excluded.target, meta=excluded.meta",
            (name, folder, kind, target, utc_now(), json.dumps(meta)))
        self.conn.commit()

    def set_status(self, name: str, status: str) -> None:
        self.conn.execute("UPDATE engines SET status=? WHERE name=?", (status, name))
        self.conn.commit()

    def engines(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM engines ORDER BY name")]
