"""SQLite mailbox. Decisions are append-only; current state is a projection."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable

from harness.contract import utc_now
from .contract import NotificationBatch


SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_batches (
  id TEXT PRIMARY KEY, template TEXT NOT NULL, title TEXT NOT NULL,
  message TEXT NOT NULL, source TEXT NOT NULL, severity TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, ai_advice TEXT, ai_confidence REAL);
CREATE TABLE IF NOT EXISTS notification_items (
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, subject TEXT NOT NULL,
  proposed_action TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT NOT NULL,
  final_value TEXT, status TEXT NOT NULL DEFAULT 'pending', decided_at TEXT, decision_note TEXT,
  FOREIGN KEY(batch_id) REFERENCES notification_batches(id));
CREATE INDEX IF NOT EXISTS ix_notification_items_batch ON notification_items(batch_id, status);
CREATE TABLE IF NOT EXISTS notification_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, decision TEXT NOT NULL,
  actor TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class NotificationStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(notification_items)")}
        if "final_value" not in columns:
            self.conn.execute("ALTER TABLE notification_items ADD COLUMN final_value TEXT")
        self.conn.commit()

    def add(self, batch: NotificationBatch) -> str:
        self.conn.execute(
            "INSERT INTO notification_batches VALUES (?,?,?,?,?,?,'pending',?,?,NULL,NULL)",
            (batch.id, batch.template, batch.title, batch.message, batch.source,
             batch.severity, batch.created_at, batch.created_at))
        self.conn.executemany(
            "INSERT INTO notification_items(id,batch_id,subject,proposed_action,summary,payload,final_value,status,decided_at,decision_note) "
            "VALUES (?,?,?,?,?,?,?,'pending',NULL,NULL)",
            [(i.id, batch.id, i.subject, i.proposed_action, i.summary,
              json.dumps(i.payload, ensure_ascii=False), i.proposed_action) for i in batch.items])
        self.conn.commit()
        return batch.id

    def batches(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM notification_batches"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"; args = (status,)
        sql += " ORDER BY created_at DESC"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def items(self, batch_id: str, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM notification_items WHERE batch_id=?"
        args: tuple = (batch_id,)
        if status:
            sql += " AND status=?"; args = (batch_id, status)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY rowid", args)]

    def decide(self, item_ids: Iterable[str], decision: str, actor: str = "David",
               note: str = "") -> int:
        now, changed = utc_now(), 0
        for item_id in item_ids:
            cur = self.conn.execute(
                "UPDATE notification_items SET status=?,decided_at=?,decision_note=? "
                "WHERE id=? AND status='pending'", (decision, now, note, item_id))
            if cur.rowcount:
                changed += 1
                self.conn.execute(
                    "INSERT INTO notification_decisions(item_id,decision,actor,note,created_at) "
                    "VALUES (?,?,?,?,?)", (item_id, decision, actor, note, now))
        batch_ids = {r[0] for item_id in item_ids for r in self.conn.execute(
            "SELECT batch_id FROM notification_items WHERE id=?", (item_id,))}
        for batch_id in batch_ids:
            pending = self.conn.execute(
                "SELECT COUNT(*) FROM notification_items WHERE batch_id=? AND status='pending'",
                (batch_id,)).fetchone()[0]
            status = "pending" if pending else "decided"
            self.conn.execute("UPDATE notification_batches SET status=?,updated_at=? WHERE id=?",
                              (status, now, batch_id))
        self.conn.commit()
        return changed

    def set_advice(self, batch_id: str, advice: str, confidence: float | None = None) -> None:
        self.conn.execute(
            "UPDATE notification_batches SET ai_advice=?,ai_confidence=?,updated_at=? WHERE id=?",
            (advice, confidence, utc_now(), batch_id))
        self.conn.commit()

    def set_final_value(self, item_id: str, value: str) -> None:
        self.conn.execute("UPDATE notification_items SET final_value=? WHERE id=? AND status='pending'",
                          (value, item_id))
        self.conn.commit()
