"""Clipboard adapter — your copies (and Ditto's paste times) as events.

Two ways in:
  ditto   read Ditto's own SQLite history (copies, plus each clip's last paste)
  watch   no Ditto? poll the clipboard with tkinter (zero installs) and log each
          new copy straight into the ledger until you Ctrl+C

Subject = what KIND of thing was copied (url, path, code, email, number, phone,
json, text) — that's the stream the engines can learn. The content itself stays
in context as a short hash + 80-char preview, never the full text.
Optional: --ollama <model> asks your local Ollama for a one-word topic label.

    python -m harness.adapters.clipboard ditto                  (default %APPDATA%\\Ditto\\Ditto.db)
    python -m harness.adapters.clipboard ditto "D:\\Ditto\\Ditto.db"
    python -m harness.adapters.clipboard watch [--ollama llama3.2]

CopyQ keeps its history in binary tab files, not SQLite — not supported here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from harness.contract import Event

DEFAULT_DITTO = Path(os.environ.get("APPDATA", "")) / "Ditto" / "Ditto.db"

_RULES = [
    ("url", re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.I)),
    ("email", re.compile(r"^\s*[\w.+-]+@[\w-]+\.[\w.-]+\s*$")),
    ("path", re.compile(r"^\s*([A-Za-z]:\\|\\\\|/|~/)[^\n]*$")),
    ("phone", re.compile(r"^\s*\+?[\d\s().-]{7,}\s*$")),
    ("number", re.compile(r"^\s*-?[\d,]+(\.\d+)?\s*%?\s*$")),
]
_CODE = re.compile(r"(\bdef |\bclass |\bimport |\bfunction\b|=>|;\s*$|^\s*[{}]\s*$|\bSELECT\b|\breturn\b)", re.M)


def kind_of(text: str) -> str:
    """Rule-based content type. Cheap, deterministic, explainable."""
    t = text.strip()
    if not t:
        return "empty"
    for name, rx in _RULES:
        if rx.match(t):
            return name
    if t[:1] in "{[":
        try:
            json.loads(t); return "json"
        except ValueError:
            pass
    if len(_CODE.findall(t)) >= 2:
        return "code"
    return "text" if len(t) < 400 else "longtext"


def ollama_topic(text: str, model: str, host: str = "http://localhost:11434") -> str:
    """One-word topic from the local model. Returns '' on any failure — never blocks ingest."""
    body = json.dumps({"model": model, "stream": False,
                       "prompt": "Give ONE lowercase word naming the topic of this clipboard text. "
                                 "Answer with the word only.\n\n" + text[:1500]}).encode()
    try:
        req = urllib.request.Request(f"{host}/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            word = json.loads(r.read()).get("response", "").strip().lower()
        return re.sub(r"[^a-z0-9_-]", "", word.split()[0]) if word else ""
    except Exception:  # noqa: BLE001
        return ""


def to_event(text: str, when: dt.datetime, action: str = "copy", source: str = "clipboard",
             ollama_model: str | None = None, extra: dict | None = None) -> Event:
    h = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:12]
    ctx = {"hash": h, "preview": text.strip().replace("\n", " ")[:80], "length": len(text),
           "hour": when.hour, "dow": when.weekday(), **(extra or {})}
    if ollama_model:
        ctx["topic"] = ollama_topic(text, ollama_model)
    ts = when.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    return Event(subject=kind_of(text), action=action, context=ctx, source=source, timestamp=ts,
                 id=f"clip_{action}_{h}_{int(when.timestamp())}")


def read_ditto(db_path: str | Path = DEFAULT_DITTO, ollama_model: str | None = None) -> list[Event]:
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"Ditto database not found: {src}")
    tmp = Path(tempfile.mkdtemp()) / "Ditto.db"
    shutil.copy2(src, tmp)                       # Ditto may hold the file open
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(Main)")}
    if not {"lDate", "mText"} <= cols:
        raise RuntimeError(f"unexpected Ditto schema, Main has: {sorted(cols)}")
    paste_col = "lastPasteDate" if "lastPasteDate" in cols else None
    group_filter = "WHERE COALESCE(bIsGroup,0)=0" if "bIsGroup" in cols else ""
    sql = f"SELECT lDate, mText{', ' + paste_col if paste_col else ''} FROM Main {group_filter} ORDER BY lDate ASC"
    out = []
    for r in conn.execute(sql):
        text = r["mText"] or ""
        if not text.strip():
            continue                              # image/file clips: Ditto stores them in Data, skip
        out.append(to_event(text, dt.datetime.fromtimestamp(int(r["lDate"]), dt.timezone.utc),
                            source="ditto", ollama_model=ollama_model))
        if paste_col and r[paste_col]:
            out.append(to_event(text, dt.datetime.fromtimestamp(int(r[paste_col]), dt.timezone.utc),
                                action="paste", source="ditto"))
    conn.close()
    return out


def watch(runner, interval: float = 1.0, ollama_model: str | None = None) -> None:
    """Poll the clipboard; every new text becomes an event in the ledger. Ctrl+C to stop."""
    import tkinter as tk
    root = tk.Tk(); root.withdraw()
    last = None
    print("watching clipboard — Ctrl+C to stop")
    try:
        while True:
            try:
                text = root.clipboard_get()
            except tk.TclError:
                text = None                       # clipboard empty or non-text
            if text and text != last:
                last = text
                e = to_event(text, dt.datetime.now().astimezone(), source="clipboard_watch", ollama_model=ollama_model)
                runner.ingest([e], refit=False)
                print(f"{e.timestamp}  {e.subject:8s}  {e.context['preview'][:60]}")
            root.update()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        root.destroy()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.runner import Runner
    args = sys.argv[1:]
    model = None
    if "--ollama" in args:
        i = args.index("--ollama"); model = args[i + 1]; del args[i:i + 2]
    mode = args[0] if args else "ditto"
    if mode == "watch":
        watch(Runner(context_keys=("subject",)), ollama_model=model)
    else:
        evs = read_ditto(args[1] if len(args) > 1 else DEFAULT_DITTO, ollama_model=model)
        print(f"read {len(evs)} clipboard events; ingested {Runner(context_keys=('subject',)).ingest(evs)} new")
