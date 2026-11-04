"""Facade used by any program that needs a visible, reviewable decision mailbox."""
from __future__ import annotations

import threading

from harness.ledger import Ledger
from .contract import NotificationBatch, NotificationItem, NotificationTemplate
from .desktop import notify
from .forge import advise
from .store import NotificationStore
from .catalog import validate
from .triage import band, may_auto_approve


class NotificationEngine:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.store = NotificationStore(ledger.conn)

    def submit(self, template: str, title: str, message: str,
               source: str, items: list[NotificationItem], severity: str = "normal",
               desktop: bool = True, auto_advise: bool = True) -> str:
        validate(template)
        batch = NotificationBatch(template, title, message, source, items, severity)
        batch_id = self.store.add(batch)
        safe_ids = [item.id for item in items if may_auto_approve(item.payload)]
        if safe_ids:
            self.store.decide(safe_ids, "approved", actor="policy:auto-safe",
                              note="High confidence; source explicitly marked read-only/additive and auto-approvable.")
        if auto_advise and any(band(item.payload.get("confidence")) == "mixed" for item in items):
            def get_advice() -> None:
                try:
                    self.request_advice(batch_id)
                except Exception:
                    pass  # the inbox remains pending and usable when Forge is offline
            threading.Thread(target=get_advice, daemon=True).start()
        if desktop:
            notify(title, f"{len(items)} item(s) need review — {message[:120]}")
        return batch_id

    def request_advice(self, batch_id: str) -> str:
        batch = next((b for b in self.store.batches() if b["id"] == batch_id), None)
        if not batch:
            raise KeyError(batch_id)
        text, confidence = advise(batch, self.store.items(batch_id))
        self.store.set_advice(batch_id, text, confidence)
        return text
