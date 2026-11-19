"""Starter fixers: breaks we already know how to fix by hand.

Each one is a mistake we fixed before, written down once as code.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import Fix, fixer

# --- Windows console can't print a character (cp1252) ----------------------
UTF8_LINE = 'import sys\nif hasattr(sys.stdout, "reconfigure"):\n    sys.stdout.reconfigure(encoding="utf-8", errors="replace")\n    sys.stderr.reconfigure(encoding="utf-8", errors="replace")\n'


@fixer("py.UnicodeEncodeError")
def utf8_stdout(stop, root: Path):
    if "charmap" not in stop.why and "encode" not in stop.why:
        return None
    entry = _entry_script(stop, root)
    if not entry:
        return None
    text = (root / entry).read_text(encoding="utf-8")
    if "reconfigure(encoding" in text:
        return None
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or lines[i].startswith("# -*-")):
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):  # keep docstring first
        q = lines[i].lstrip()[:3]
        if lines[i].count(q) < 2:
            i += 1
            while i < len(lines) and q not in lines[i]:
                i += 1
        i += 1
    while i < len(lines) and lines[i].startswith("from __future__"):
        i += 1
    new = "".join(lines[:i]) + UTF8_LINE + "".join(lines[i:])
    return Fix("Windows console is cp1252; force UTF-8 stdout/stderr in the entry script",
               [{"file": entry, "content": new}])


# --- Mojibake (UTF-8 read as cp1252) in a text/HTML file ---------------------
MOJIBAKE = {"â€™": "’", "â€œ": "“", "â€\x9d": "”", "â€”": "—", "â€“": "–",
            "â€¦": "…", "Ã©": "é", "Â ": " ", "Â·": "·"}


@fixer("html.mojibake")
def fix_mojibake(stop, root: Path):
    edits = []
    for rel in stop.files:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        new = text
        for bad, good in MOJIBAKE.items():
            new = new.replace(bad, good)
        if new != text:
            edits.append({"file": rel, "content": new})
    return Fix("Replace known mojibake tokens with the intended characters", edits) if edits else None


# --- Opening a text file without encoding on Windows ------------------------
@fixer("py.UnicodeDecodeError")
def open_with_utf8(stop, root: Path):
    if "charmap" not in stop.why or not stop.files:
        return None
    rel, line_no = _frame(stop)
    if not rel:
        return None
    lines = (root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
    ln = lines[line_no - 1]
    new_ln = re.sub(r"\b(open|read_text)\(([^()]*)\)",
                    lambda m: m.group(0) if "encoding" in m.group(2)
                    else f'{m.group(1)}({m.group(2)}{", " if m.group(2).strip() else ""}encoding="utf-8")', ln)
    if new_ln == ln:
        return None
    lines[line_no - 1] = new_ln
    return Fix("File read with Windows default codec; pass encoding='utf-8'",
               [{"file": rel, "content": "".join(lines)}])


def _entry_script(stop, root: Path) -> str | None:
    for part in stop.resume:
        if part.endswith(".py") and (root / part).is_file():
            return part
    return stop.files[0] if stop.files else None


def _frame(stop) -> tuple[str | None, int]:
    m = re.match(r"(.+):(\d+)$", stop.where)
    if not m:
        return None, 0
    p = Path(m.group(1))
    name = p.name
    rel = next((f for f in stop.files if Path(f).name == name), None)
    return rel, int(m.group(2))
