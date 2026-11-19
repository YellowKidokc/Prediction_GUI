"""Fixer registry: error code -> code WE wrote that fixes it.

This is tier 0 and the whole point: every time we fix a mistake by hand, we
write it here once under its error code, and the loop fixes that code forever
after without calling a model.

A fixer is a function  fn(stop, root) -> Fix | None
  - return None when it does not apply to this particular stop
  - return Fix(summary, edits) where edits = [{"file": rel_path, "content": full_new_text}]
The ladder still proves every fix in a sandbox rerun before applying it.

Add a fixer: drop a module in this folder (or promote one from drafts/) and use

    from unsticker.fixers import fixer, Fix

    @fixer("py.UnicodeEncodeError")
    def utf8_stdout(stop, root): ...

Codes look like  py.<ExceptionName>, html.<error_type>, proc.exit<N>.
A code may have several fixers; they are tried in registration order.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

REGISTRY: dict[str, list[Callable]] = {}


@dataclass
class Fix:
    summary: str
    edits: list[dict] = field(default_factory=list)


def fixer(*codes: str):
    def wrap(fn: Callable) -> Callable:
        for c in codes:
            REGISTRY.setdefault(c, []).append(fn)
        return fn
    return wrap


def for_code(code: str) -> list[Callable]:
    return REGISTRY.get(code, []) + REGISTRY.get("*", [])


_loaded_projects: set[str] = set()


def load_project(root) -> int:
    """Load <project>/.unsticker/fixers.py (and fixers/*.py) so project-only fixes
    live with the project. Project fixers register like central ones and run first."""
    from pathlib import Path
    import importlib.util
    base = Path(root) / ".unsticker"
    files = [base / "fixers.py"] + sorted((base / "fixers").glob("*.py"))
    n = 0
    for f in files:
        if not f.is_file() or str(f) in _loaded_projects:
            continue
        before = {k: list(v) for k, v in REGISTRY.items()}
        spec = importlib.util.spec_from_file_location(f"unsticker_project_{abs(hash(str(f)))}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for code, fns in REGISTRY.items():  # move the new project fixers to the front
            new = [fn for fn in fns if fn not in before.get(code, [])]
            REGISTRY[code] = new + [fn for fn in fns if fn not in new]
            n += len(new)
        _loaded_projects.add(str(f))
    return n


def _load() -> None:
    for mod in pkgutil.iter_modules(__path__):
        if not mod.name.startswith("_") and mod.name != "drafts":
            importlib.import_module(f"{__name__}.{mod.name}")


_load()
