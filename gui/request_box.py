"""Request box: the front door in a window.

Type what you want -> "Understand" (a model turns it into a job spec) -> read or
edit the spec -> "Run" (runs inside the unsticker loop, live log below) ->
results arrive in the notification inbox with a toast.

Standalone:  python -m gui.request_box      (or REQUEST.bat)
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontdoor.spec import JOB_TYPES, translate, validate  # noqa: E402

OUT = ROOT / "frontdoor" / "out"
EXAMPLE = ("Normalize the names of the series folders directly inside "
           "\\\\192.168.2.50\\h_hp\\Documents\\B_series, up to 40 of them, so each is just the series name")


class RequestBox(tk.Toplevel):
    def __init__(self, parent: tk.Misc, on_inbox=None) -> None:
        super().__init__(parent)
        self.title("Request — tell it what you want done")
        self.geometry("980x720")
        self.on_inbox = on_inbox
        self.q: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self._build()
        self.after(100, self._drain)

    # ---------- layout ----------
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="What do you want done?  (plain English)").pack(anchor="w", **pad)
        self.req = tk.Text(self, height=4, wrap="word", font=("Segoe UI", 11))
        self.req.pack(fill="x", **pad)
        self.req.insert("1.0", EXAMPLE)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        self.btn_understand = ttk.Button(row, text="1. Understand →", command=self.understand)
        self.btn_understand.pack(side="left")
        self.btn_run = ttk.Button(row, text="2. Run it", command=self.run, state="disabled")
        self.btn_run.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left")
        if self.on_inbox:
            ttk.Button(row, text="Open inbox", command=self.on_inbox).pack(side="right")
        jobs = ", ".join(JOB_TYPES)
        ttk.Label(row, text=f"jobs it can do: {jobs}", foreground="#666").pack(side="right", padx=10)

        self.understood = ttk.Label(self, text="", foreground="#1a5", wraplength=940, justify="left")
        self.understood.pack(anchor="w", **pad)

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, **pad)
        f1 = ttk.LabelFrame(panes, text="Job spec (you can edit before running)")
        self.spec = tk.Text(f1, height=12, font=("Consolas", 10))
        self.spec.pack(fill="both", expand=True)
        f2 = ttk.LabelFrame(panes, text="Live log")
        self.log = tk.Text(f2, height=14, font=("Consolas", 10), background="#111", foreground="#ddd")
        self.log.pack(fill="both", expand=True)
        panes.add(f1, weight=1)
        panes.add(f2, weight=2)

        self.status = ttk.Label(self, text="Ready.", anchor="w")
        self.status.pack(fill="x", **pad)

    # ---------- helpers ----------
    def _say(self, text: str) -> None:
        self.q.put(("log", text))

    def _drain(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", val.rstrip() + "\n")
                    self.log.see("end")
                elif kind == "spec":
                    self._show_spec(val)
                elif kind == "error":
                    self.status.config(text=val)
                    self.btn_understand.config(state="normal")
                    messagebox.showerror("Request", val, parent=self)
                elif kind == "done":
                    self.status.config(text=val)
                    self.btn_run.config(state="normal")
                    self.btn_understand.config(state="normal")
                    self.btn_stop.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _show_spec(self, spec: dict) -> None:
        self.understood.config(text="I understood: " + spec.get("understood", ""))
        self.spec.delete("1.0", "end")
        self.spec.insert("1.0", json.dumps(spec, indent=1, ensure_ascii=False))
        self.btn_understand.config(state="normal")
        self.btn_run.config(state="normal")
        self.status.config(text=f"Spec ready (translated by {spec.get('_translated_by', '?')}). "
                                "Check it, then Run.")

    # ---------- actions ----------
    def understand(self) -> None:
        text = self.req.get("1.0", "end").strip()
        if not text:
            return
        self.btn_understand.config(state="disabled")
        self.btn_run.config(state="disabled")
        self.status.config(text="Asking the model to understand the request…")

        def work() -> None:
            try:
                self.q.put(("spec", translate(text)))
            except Exception as exc:
                self.q.put(("error", f"Couldn't understand it: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        try:
            spec = validate(json.loads(self.spec.get("1.0", "end")))
        except Exception as exc:
            messagebox.showerror("Spec", f"The spec isn't valid: {exc}", parent=self)
            return
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"spec_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
        self.btn_run.config(state="disabled")
        self.btn_understand.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status.config(text="Running (inside the unsticker loop)…")
        self._say(f"--- run {path.name} ---")

        def work() -> None:
            cmd = [sys.executable, "-u", "-m", "frontdoor", "--yes", "--spec", str(path)]
            try:
                self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                             errors="replace", env={**__import__("os").environ,
                                                                    "PYTHONIOENCODING": "utf-8"},
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in self.proc.stdout:
                    self._say(line)
                code = self.proc.wait()
                self.q.put(("done", "Done — results are in the notification inbox." if code == 0
                            else f"Finished with exit {code}; see the log (stuck cases go to the inbox)."))
            except Exception as exc:
                self.q.put(("done", f"Run failed to start: {exc}"))
            finally:
                self.proc = None
        threading.Thread(target=work, daemon=True).start()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._say("--- stopped by you ---")


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    def open_inbox() -> None:
        try:
            from harness.runner import Runner
            from notifications import NotificationEngine
            from gui.notification_inbox import NotificationInbox
            NotificationInbox(root, NotificationEngine(Runner().ledger))
        except Exception as exc:
            messagebox.showerror("Inbox", str(exc))

    box = RequestBox(root, on_inbox=open_inbox)
    box.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
