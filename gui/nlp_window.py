"""NLP pipeline window: pick folder + goal -> DeepSeek plans -> run -> read -> revise -> lock."""
from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from nlp import llm, steps
from nlp.pipeline import Pipeline
from notifications import NotificationItem, NotificationTemplate


class NLPWindow(tk.Toplevel):
    def __init__(self, parent, notifications=None) -> None:
        super().__init__(parent)
        self.notifications = notifications
        self.title("NLP pipelines — DeepSeek plans, you lock")
        self.geometry("1300x760")
        self.pipe: Pipeline | None = None
        self._q: queue.Queue = queue.Queue()
        self._build(); self._load_list(); self._pump()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Label(top, text="Pipeline:").pack(side="left")
        self.name = ttk.Combobox(top, width=24); self.name.pack(side="left")
        self.name.bind("<<ComboboxSelected>>", lambda e: self.open_pipe())
        ttk.Button(top, text="Open", command=self.open_pipe).pack(side="left", padx=2)
        ttk.Label(top, text="  Folder:").pack(side="left")
        self.folder = ttk.Entry(top, width=50); self.folder.pack(side="left")
        ttk.Button(top, text="Browse…", command=self.browse).pack(side="left", padx=2)
        self.state_lbl = ttk.Label(top, text="", foreground="#06c"); self.state_lbl.pack(side="right")

        g = ttk.Frame(self, padding=(6, 0)); g.pack(fill="x")
        ttk.Label(g, text="Goal (plain English):").pack(side="left")
        self.goal = ttk.Entry(g); self.goal.pack(side="left", fill="x", expand=True)
        self.goal.insert(0, "understand this folder: what's in it, topics, duplicates")
        ttk.Label(g, text=f"  DeepSeek via {llm.backend()}  ({os.environ.get('DEEPSEEK_MODEL', 'default model')})",
                  foreground="#666").pack(side="left")

        bar = ttk.Frame(self, padding=6); bar.pack(fill="x")
        self.btns = {}
        for label, cmd in (("1 · Plan", self.plan), ("2 · Run", self.run), ("Run sample (20 docs)", lambda: self.run(20)),
                           ("3 · Revise with feedback", self.revise), ("Save hand-edited plan", self.save_plan),
                           ("4 · Lock", self.lock), ("Unlock", self.unlock)):
            b = ttk.Button(bar, text=label, command=cmd); b.pack(side="left", padx=2); self.btns[label] = b
        avail = ", ".join(s["step"] for s in steps.describe() if s["available"])
        ttk.Label(bar, text=f"steps: {avail}", foreground="#666").pack(side="right")

        panes = ttk.Panedwindow(self, orient="horizontal"); panes.pack(fill="both", expand=True, padx=6)
        lf = ttk.Labelframe(panes, text="Plan (JSON — editable)", padding=4); panes.add(lf, weight=2)
        self.plan_txt = tk.Text(lf, wrap="none", font=("Consolas", 10)); self.plan_txt.pack(fill="both", expand=True)
        ttk.Label(lf, text="Feedback for the next revision:").pack(anchor="w")
        self.feedback = tk.Text(lf, height=4, wrap="word"); self.feedback.pack(fill="x")
        rf = ttk.Labelframe(panes, text="Last run report", padding=4); panes.add(rf, weight=3)
        self.report = tk.Text(rf, wrap="word"); self.report.pack(fill="both", expand=True)
        self.versions = ttk.Label(self, text="", foreground="#666"); self.versions.pack(anchor="w", padx=6)
        self.log = tk.Text(self, height=4, state="disabled", bg="#111", fg="#ccc"); self.log.pack(fill="x")

    # ---- helpers ------------------------------------------------------
    def _log(self, m: str) -> None:
        self.log.configure(state="normal"); self.log.insert("end", m + "\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self) -> None:
        """Worker threads never touch Tk; they queue callables and this runs them on the UI thread."""
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._pump)

    def _fail(self, msg: str) -> None:
        self.config(cursor=""); self._log("✗ " + msg); messagebox.showerror("NLP", msg, parent=self)

    def _bg(self, label: str, work, done) -> None:
        self._log(label + "…"); self.config(cursor="watch")
        def go():
            try:
                r = work(); self._q.put(lambda: (self.config(cursor=""), done(r)))
            except Exception as e:  # noqa: BLE001
                msg = str(e); self._q.put(lambda: self._fail(msg))
        threading.Thread(target=go, daemon=True).start()

    def _load_list(self) -> None:
        self.name["values"] = [p.data["name"] for p in Pipeline.all()]

    def _ensure(self) -> Pipeline | None:
        n = self.name.get().strip()
        if not n:
            messagebox.showinfo("NLP", "Give the pipeline a name first.", parent=self); return None
        if not self.pipe or self.pipe.data["name"] != Pipeline(n).data["name"]:
            self.pipe = Pipeline(n)
        return self.pipe

    def show(self) -> None:
        if not self.pipe:
            return
        p = self.pipe = Pipeline(self.pipe.data["name"])  # re-read: the inbox may have locked it
        cur = p.current
        self.plan_txt.delete("1.0", "end")
        if cur:
            self.plan_txt.insert("1.0", json.dumps(cur["plan"], indent=2))
        if p.data["folder"]:
            self.folder.delete(0, "end"); self.folder.insert(0, p.data["folder"])
        if p.data["goal"]:
            self.goal.delete(0, "end"); self.goal.insert(0, p.data["goal"])
        locked = p.data["locked"]
        self.state_lbl.configure(text=f"🔒 LOCKED v{locked}" if locked else f"draft v{cur['v'] if cur else 0}",
                                 foreground="#080" if locked else "#06c")
        for label in ("1 · Plan", "3 · Revise with feedback", "Save hand-edited plan", "4 · Lock"):
            self.btns[label].state(["disabled"] if locked else ["!disabled"])
        self.versions.configure(text="history: " + "  ".join(
            f"v{v['v']}{'*' if v['v'] == locked else ''} ({v['plan'].get('planner', 'hand')}"
            f"{': ' + v['feedback'][:30] if v['feedback'] else ''})" for v in p.data["versions"]))
        last = p.last_run()
        self.report.delete("1.0", "end")
        if last:
            self.report.insert("1.0", (last / "report.md").read_text("utf-8"))

    # ---- actions ------------------------------------------------------
    def browse(self) -> None:
        d = filedialog.askdirectory(parent=self)
        if d:
            self.folder.delete(0, "end"); self.folder.insert(0, d)
            if not self.name.get().strip():
                self.name.set(os.path.basename(d.rstrip("/\\")))

    def open_pipe(self) -> None:
        if self._ensure():
            self.show()

    def plan(self) -> None:
        p = self._ensure(); folder = self.folder.get().strip()
        if not p or not folder or not os.path.isdir(folder):
            messagebox.showinfo("NLP", "Pick an existing folder.", parent=self); return
        def done(v):
            self._log(f"plan v{v['v']} from {v['plan'].get('planner')}"
                      + (f" — {v['plan']['planner_error'][:120]}" if v["plan"].get("planner_error") else ""))
            self._load_list(); self.show()
        goal = self.goal.get().strip()
        self._bg("DeepSeek is reading the folder profile and choosing steps", lambda: p.plan(folder, goal), done)

    def run(self, limit: int | None = None) -> None:
        p = self._ensure()
        if not p:
            return
        def done(run_dir):
            self.show(); self._log(f"run saved → {run_dir}")
            if self.notifications:
                self.notifications.submit(
                    NotificationTemplate.APPROVAL_BATCH, f"NLP run ready: {p.data['name']}",
                    "Read the report; approve to lock this plan version.", "nlp.pipeline",
                    [NotificationItem(subject=f"{p.data['name']} v{p.current['v']}", proposed_action="lock",
                                      summary=str(run_dir), payload={"pipeline": p.data["name"],
                                                                     "version": p.current["v"]})],
                    auto_advise=False)
        self._bg("running", lambda: p.run(limit, progress=lambda m: self._q.put(lambda: self._log(m))), done)

    def revise(self) -> None:
        p = self._ensure(); fb = self.feedback.get("1.0", "end").strip()
        if not p or not fb:
            messagebox.showinfo("NLP", "Write what to change in the feedback box.", parent=self); return
        def done(v):
            self.feedback.delete("1.0", "end"); self._log(f"revised → v{v['v']}"); self.show()
        self._bg("DeepSeek is revising the plan", lambda: p.revise(fb), done)

    def save_plan(self) -> None:
        p = self._ensure()
        if not p:
            return
        try:
            plan = json.loads(self.plan_txt.get("1.0", "end"))
        except json.JSONDecodeError as e:
            messagebox.showerror("NLP", f"plan is not valid JSON: {e}", parent=self); return
        try:
            plan.setdefault("planner", "hand"); v = p.set_plan(plan); self._log(f"saved hand edit → v{v['v']}"); self.show()
        except RuntimeError as e:
            messagebox.showerror("NLP", str(e), parent=self)

    def lock(self) -> None:
        p = self._ensure()
        if p and messagebox.askyesno("Lock", "Freeze this plan? Runs will use it until you unlock.", parent=self):
            self._log(f"locked v{p.lock()}"); self.show()

    def unlock(self) -> None:
        p = self._ensure()
        if p:
            p.unlock(); self._log("unlocked"); self.show()
