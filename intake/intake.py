"""intake.py — drop a folder under engines/, run this on it, and it gets understood.

  python intake\intake.py engines\my_new_engine

What it does, in order:
  1. Looks at every .py in the folder: imports, argparse, tkinter/PyQt/streamlit,
     fastapi/flask, class definitions.
  2. Classifies the folder:  library | cli | gui | service | unknown
  3. Finds an Engine subclass if one exists (→ library, ready for the loop).
  4. Writes engine.json (never overwrites one that already exists — edit it by hand).
  5. Registers it in the ledger as 'shadow'.
  6. Prints what it found and, if it is not a library, what wrapper is needed.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.ledger import Ledger          # noqa: E402
from harness.runner import DB_PATH         # noqa: E402

GUI_LIBS = {"tkinter", "PyQt5", "PyQt6", "PySide6", "wx", "streamlit", "gradio", "dearpygui", "customtkinter"}
SERVICE_LIBS = {"fastapi", "flask", "uvicorn", "aiohttp", "bottle"}
ML_LIBS = {"sklearn", "torch", "tensorflow", "keras", "xgboost", "lightgbm", "statsmodels", "prophet"}


def inspect_py(path: Path) -> dict:
    info = {"file": path.name, "imports": set(), "argparse": False, "main": False,
            "classes": [], "engine_class": None}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        info["error"] = f"syntax: {e}"
        return info
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info["imports"].update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            info["imports"].add(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            bases = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases]
            info["classes"].append(node.name)
            if "Engine" in bases:
                info["engine_class"] = node.name
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            src = ast.get_source_segment(path.read_text(encoding="utf-8", errors="replace"), node.test) or ""
            if "__main__" in src:
                info["main"] = True
    info["argparse"] = "argparse" in info["imports"] or "click" in info["imports"] or "typer" in info["imports"]
    return info


def classify(reports: list[dict]) -> tuple[str, dict | None]:
    """Return (kind, the report that carries the Engine subclass if any)."""
    for r in reports:
        if r.get("engine_class"):
            return "library", r
    imports = set().union(*(r["imports"] for r in reports if "imports" in r))
    if imports & GUI_LIBS:
        return "gui", None
    if imports & SERVICE_LIBS:
        return "service", None
    if any(r.get("argparse") or r.get("main") for r in reports):
        return "cli", None
    return "unknown", None


def intake(folder: Path) -> dict:
    folder = folder.resolve()
    if not folder.is_dir():
        raise SystemExit(f"not a folder: {folder}")
    py_files = [p for p in folder.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]
    reports = [inspect_py(p) for p in py_files]
    kind, engine_report = classify(reports)
    all_imports = sorted(set().union(*(r["imports"] for r in reports if "imports" in r)))
    meta_path = folder / "engine.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        wrote = False
    else:
        meta = {"name": folder.name, "kind": kind,
                "entry": engine_report["file"] if engine_report else (py_files[0].name if py_files else ""),
                "class": engine_report["engine_class"] if engine_report else "",
                "target": "next_subject", "describe": "", "author": "", "status": "shadow",
                "uses_ml": sorted(set(all_imports) & ML_LIBS), "imports": all_imports,
                "py_files": [str(p.relative_to(folder)) for p in py_files]}
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        wrote = True
    Ledger(DB_PATH).register_engine(meta["name"], str(folder), meta.get("kind", kind), meta.get("target", "?"), meta)
    return {"folder": str(folder), "kind": meta.get("kind", kind), "entry": meta.get("entry"),
            "class": meta.get("class"), "py_files": len(py_files), "imports": all_imports,
            "wrote_engine_json": wrote, "ml": sorted(set(all_imports) & ML_LIBS)}


NEXT = {
    "library": "Ready. It runs in the loop as of the next RUN_GUI / RUN_SHADOW.",
    "cli":     "Needs engine.py wrapper: subclass Engine, call the CLI in predict(), parse its output into Candidates.",
    "gui":     "GUI engines cannot run in the loop. Wrap the model code (not the window) in an Engine subclass.",
    "service": "Needs engine.py wrapper that POSTs context to the service and maps the reply to Candidates.",
    "unknown": "No Engine subclass, no CLI, no GUI detected. Copy engines/_TEMPLATE/engine.py in and fill it.",
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python intake\\intake.py engines\\<folder>")
    r = intake(Path(sys.argv[1]))
    print(json.dumps(r, indent=2))
    print("\nNEXT:", NEXT.get(r["kind"], NEXT["unknown"]))
