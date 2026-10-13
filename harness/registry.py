"""Registry — finds engines under engines/<name>/, loads them, keeps the ledger's
engine table in sync.

An engine folder is valid when it has:
  engine.json   {"name": ..., "kind": "library"|"cli"|"gui"|"service", "entry": "engine.py",
                 "class": "MyEngine", "target": "next_channel", ...}
  <entry>       a .py file defining the class named in engine.json (Engine subclass)
intake/intake.py writes engine.json for you when you drop a folder in.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from .contract import Engine
from .ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
ENGINES_DIR = ROOT / "engines"


def _load_class(py_file: Path, class_name: str) -> type[Engine]:
    spec = importlib.util.spec_from_file_location(f"pgui_engine_{py_file.parent.name}", py_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {py_file}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    cls = getattr(mod, class_name)
    if not (isinstance(cls, type) and issubclass(cls, Engine)):
        raise TypeError(f"{class_name} in {py_file} is not an Engine subclass")
    return cls


def discover() -> list[dict[str, Any]]:
    """Every folder under engines/ with an engine.json. Folders starting with '_' are skipped."""
    found = []
    for d in sorted(ENGINES_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        meta_path = d / "engine.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            found.append({"name": d.name, "folder": str(d), "error": f"bad engine.json: {e}"})
            continue
        meta.setdefault("name", d.name)
        meta["folder"] = str(d)
        found.append(meta)
    return found


def load(meta: dict[str, Any]) -> Engine:
    if meta.get("kind", "library") != "library":
        raise RuntimeError(f"{meta['name']}: kind={meta.get('kind')} needs a wrapper engine.py before it can run in the loop")
    py_file = Path(meta["folder"]) / meta.get("entry", "engine.py")
    cls = _load_class(py_file, meta.get("class", "Engine"))
    inst = cls(**meta.get("params", {}))    # engine.json "params" -> constructor kwargs
    inst.name = meta["name"]
    inst.target = meta.get("target", inst.target)
    return inst


def sync(ledger: Ledger) -> list[dict[str, Any]]:
    """Discover, register everything valid in the ledger, return the list with load status."""
    report = []
    for meta in discover():
        if "error" in meta:
            report.append(meta); continue
        try:
            eng = load(meta)
            ledger.register_engine(meta["name"], meta["folder"], meta.get("kind", "library"), eng.target, meta)
            report.append({**meta, "loaded": True, "target": eng.target})
        except Exception as e:  # noqa: BLE001 — report, never crash the loop
            ledger.register_engine(meta["name"], meta["folder"], meta.get("kind", "library"), meta.get("target", "?"), meta)
            report.append({**meta, "loaded": False, "error": str(e)})
    return report
