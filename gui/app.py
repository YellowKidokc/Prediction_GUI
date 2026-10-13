"""Prediction_GUI — the one window.

Left:   engines (checkbox = include in this shadow run), status, hit-rate
Middle: situation (context) + Shadow button; the predictions table
Right:  outcome entry + Resolve; the scoreboard
Bottom: log

Zero dependencies — tkinter ships with Python.
"""
from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.runner import Runner                      # noqa: E402
from harness.adapters import csv_events                # noqa: E402

try:
    from harness.adapters import chrome_history         # noqa: E402
except Exception:  # noqa: BLE001
    chrome_history = None


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Prediction_GUI — shadow harness")
        self.geometry("1180x720")
        self.runner = Runner(context_keys=("subject",))
        self.engine_vars: dict[str, tk.BooleanVar] = {}
        self._build()
        self.refresh()

    # ---- layout -------------------------------------------------------
    def _build(self) -> None:
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Reload engines", command=self.reload).pack(side="left")
        ttk.Button(top, text="Ingest CSV…", command=self.ingest_csv).pack(side="left", padx=4)
        ttk.Button(top, text="Ingest Chrome YouTube history", command=self.ingest_chrome).pack(side="left", padx=4)
        self.lbl_events = ttk.Label(top, text="events: 0"); self.lbl_events.pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True)

        # left: engines
        left = ttk.Labelframe(body, text="Engines (engines/<name>/engine.json)", padding=6)
        self.engine_box = ttk.Frame(left); self.engine_box.pack(fill="both", expand=True)
        body.add(left, weight=1)

        # middle: situation + predictions
        mid = ttk.Frame(body, padding=6); body.add(mid, weight=3)
        sit = ttk.Labelframe(mid, text="Situation (context as JSON)  — e.g. {\"subject\": \"\", \"hour\": 21}", padding=6)
        sit.pack(fill="x")
        self.ctx = tk.Text(sit, height=3); self.ctx.insert("1.0", "{\"hour\": 21, \"dow\": 1}"); self.ctx.pack(fill="x")
        ttk.Button(sit, text="Shadow run → every checked engine predicts", command=self.shadow).pack(anchor="e", pady=4)
        cols = ("engine", "target", "top", "conf", "guidance")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (150, 110, 220, 60, 420)):
            self.tree.heading(c, text=c); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=6)

        # right: outcome + scoreboard
        right = ttk.Frame(body, padding=6); body.add(right, weight=2)
        res = ttk.Labelframe(right, text="Outcome arrived", padding=6); res.pack(fill="x")
        ttk.Label(res, text="what actually happened (value):").pack(anchor="w")
        self.outcome = ttk.Entry(res); self.outcome.pack(fill="x")
        ttk.Button(res, text="Resolve → score open predictions for this situation", command=self.resolve).pack(anchor="e", pady=4)
        sb = ttk.Labelframe(right, text="Scoreboard (last 200 resolved)", padding=6); sb.pack(fill="both", expand=True)
        scols = ("engine", "status", "scored", "hits", "hit_rate", "pending")
        self.score = ttk.Treeview(sb, columns=scols, show="headings", height=12)
        for c, w in zip(scols, (150, 70, 60, 50, 70, 60)):
            self.score.heading(c, text=c); self.score.column(c, width=w, anchor="center")
        self.score.pack(fill="both", expand=True)

        self.log = tk.Text(self, height=6, state="disabled", bg="#111", fg="#ccc"); self.log.pack(fill="x")

    # ---- actions ------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.log.configure(state="normal"); self.log.insert("end", msg + "\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def refresh(self) -> None:
        for w in self.engine_box.winfo_children():
            w.destroy()
        self.engine_vars = {}
        for name, eng in self.runner.engines.items():
            v = tk.BooleanVar(value=True); self.engine_vars[name] = v
            ttk.Checkbutton(self.engine_box, text=f"{name}  →  {eng.target}", variable=v).pack(anchor="w")
        for name, err in self.runner.errors.items():
            ttk.Label(self.engine_box, text=f"✗ {name}: {err[:70]}", foreground="#c44").pack(anchor="w")
        self.lbl_events.configure(text=f"events: {self.runner.ledger.event_count()}")
        self.score.delete(*self.score.get_children())
        for row in self.runner.scoreboard():
            self.score.insert("", "end", values=(row["engine"], row["status"], row["scored"], row["hits"],
                                                 "" if row["hit_rate"] is None else f"{row['hit_rate']:.0%}", row["pending"]))

    def reload(self) -> None:
        self.runner.reload_engines(); self.refresh()
        self._log(f"reloaded: {len(self.runner.engines)} engines, {len(self.runner.errors)} with errors")

    def _context(self) -> dict | None:
        try:
            return json.loads(self.ctx.get("1.0", "end").strip() or "{}")
        except json.JSONDecodeError as e:
            messagebox.showerror("context", f"not valid JSON: {e}"); return None

    def shadow(self) -> None:
        ctx = self._context()
        if ctx is None:
            return
        self.tree.delete(*self.tree.get_children())
        keep = {n for n, v in self.engine_vars.items() if v.get()}
        hidden = {n: e for n, e in self.runner.engines.items() if n not in keep}
        for n in hidden: self.runner.engines.pop(n)
        try:
            preds = self.runner.shadow(ctx)
        finally:
            self.runner.engines.update(hidden)
        for p in preds:
            t = p.top
            self.tree.insert("", "end", values=(p.engine, p.target, t.value if t else "—",
                                                f"{t.confidence:.2f}" if t else "", p.guidance))
        self._log(f"shadow: {len(preds)} predictions logged for {ctx}"); self.refresh()

    def resolve(self) -> None:
        ctx = self._context(); val = self.outcome.get().strip()
        if ctx is None or not val:
            return
        n = self.runner.resolve(ctx, val)
        self._log(f"resolved {n} predictions with outcome={val!r}"); self.refresh()

    def ingest_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        evs = csv_events.read(path)
        n = self.runner.ingest(evs)
        self._log(f"csv: read {len(evs)}, {n} new"); self.refresh()

    def ingest_chrome(self) -> None:
        if chrome_history is None:
            messagebox.showerror("chrome", "adapter failed to import"); return
        def work():
            try:
                evs = chrome_history.read()
                n = self.runner.ingest(evs)
                self.after(0, lambda: (self._log(f"chrome: {len(evs)} youtube visits, {n} new"), self.refresh()))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("chrome", str(e)))
        threading.Thread(target=work, daemon=True).start()
        self._log("chrome: reading History (copying first, Chrome holds a lock)…")


if __name__ == "__main__":
    App().mainloop()
