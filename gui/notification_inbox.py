"""One spreadsheet-like grid for every notification and approval type."""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from notifications.triage import band


class NotificationInbox(tk.Toplevel):
    def __init__(self, parent, engine) -> None:
        super().__init__(parent)
        self.engine, self.checked = engine, set()
        self.title("Notification & Approval Grid")
        self.geometry("1450x720")
        self._build(); self.refresh()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8); top.pack(fill="x")
        for label, command in (
            ("Refresh", self.refresh), ("Check all pending", self.check_all),
            ("Clear checks", self.clear_checks),
            ("Approve checked", lambda: self.decide("approved")),
            ("Hold checked", lambda: self.decide("held")),
            ("Reject checked", lambda: self.decide("rejected"))):
            ttk.Button(top, text=label, command=command).pack(side="left", padx=2)
        ttk.Button(top, text="Ask AI about checked batch", command=self.ask_ai).pack(side="right")

        cols = ("check", "number", "current", "proposed", "confidence", "final", "reason", "life", "status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        labels = ("✓", "#", "Current value / file name", "Prediction", "Confidence", "Final value (editable)", "Reason", "Life", "Decision")
        widths = (38, 45, 240, 210, 80, 230, 330, 45, 90)
        for c, label, width in zip(cols, labels, widths):
            self.tree.heading(c, text=label); self.tree.column(c, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.tag_configure("high", background="#dff3df")
        self.tree.tag_configure("mixed", background="#fff0bd")
        self.tree.tag_configure("low", background="#ffd9d9")
        self.tree.tag_configure("unknown", background="#eeeeee")
        self.tree.bind("<Button-1>", self.click)
        self.tree.bind("<Double-1>", self.edit_final)
        ttk.Label(self, text="Click the ✓ column to check rows. Double-click Final value to edit it before approval.").pack(anchor="w", padx=8)
        self.detail = tk.Text(self, height=9, wrap="word"); self.detail.pack(fill="x", padx=8, pady=8)

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        batches = {b["id"]: b for b in self.engine.store.batches()}
        number = 0
        for batch_id, batch in batches.items():
            for item in self.engine.store.items(batch_id):
                number += 1
                payload = json.loads(item["payload"] or "{}")
                confidence = payload.get("confidence")
                confidence = f"{float(confidence):.0%}" if confidence is not None else ""
                review_band = band(payload.get("confidence"))
                self.tree.insert("", "end", iid=item["id"], tags=(batch_id, review_band), values=(
                    "☑" if item["id"] in self.checked else "☐", number,
                    payload.get("current_value", item["subject"]), item["proposed_action"], confidence,
                    item["final_value"] or item["proposed_action"], item["summary"], item["lifecycle_code"], item["status"]))

    def click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.set(iid, "status") != "pending": return
        self.checked.symmetric_difference_update({iid}); self.refresh()

    def edit_final(self, event) -> None:
        if self.tree.identify_column(event.x) != "#6": return
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.set(iid, "status") != "pending": return
        value = simpledialog.askstring("Edit final value", "Final value or file name:",
                                       initialvalue=self.tree.set(iid, "final"), parent=self)
        if value is not None:
            self.engine.store.set_final_value(iid, value.strip()); self.refresh()

    def check_all(self) -> None:
        self.checked = {iid for iid in self.tree.get_children() if self.tree.set(iid, "status") == "pending"}; self.refresh()

    def clear_checks(self) -> None:
        self.checked.clear(); self.refresh()

    def decide(self, decision: str) -> None:
        ids = [iid for iid in self.checked if self.tree.exists(iid)]
        if not ids: return
        changed = self.engine.store.decide(ids, decision)
        if decision == "approved":
            self._apply_nlp_locks(ids)
        self.checked.difference_update(ids); self.refresh()
        messagebox.showinfo("Approval grid", f"{changed} item(s) marked {decision}.", parent=self)

    def _apply_nlp_locks(self, ids) -> None:
        """An approved 'NLP run ready' row locks that pipeline at the version that ran."""
        from nlp.pipeline import Pipeline
        rows = self.engine.store.conn.execute(
            f"SELECT payload FROM notification_items WHERE id IN ({','.join('?' * len(ids))})", list(ids)).fetchall()
        for r in rows:
            p = json.loads(r["payload"] or "{}")
            if p.get("pipeline") and p.get("version"):
                Pipeline(p["pipeline"]).lock(int(p["version"]))

    def _one_batch(self) -> str | None:
        ids = self.checked or set(self.tree.selection())
        batch_ids = {self.tree.item(iid, "tags")[0] for iid in ids if self.tree.exists(iid)}
        if len(batch_ids) != 1:
            messagebox.showinfo("AI advice", "Check rows from one batch so the AI receives the right context.", parent=self); return None
        return next(iter(batch_ids))

    def ask_ai(self) -> None:
        batch_id = self._one_batch()
        if not batch_id: return
        self.detail.delete("1.0", "end"); self.detail.insert("1.0", "Asking Forge…")
        def work():
            try: result = self.engine.request_advice(batch_id)
            except Exception as exc: result = f"AI unavailable; nothing changed.\n\n{exc}"
            self.after(0, lambda: (self.detail.delete("1.0", "end"), self.detail.insert("1.0", result)))
        threading.Thread(target=work, daemon=True).start()
