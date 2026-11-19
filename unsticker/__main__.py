"""python -m unsticker --root PROJECT [--check "pytest -q"] -- python script.py args"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .ladder import unstick


def main() -> int:
    for s in (sys.stdout, sys.stderr):  # our own log must never die on a cp1252 console
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    i = sys.argv.index("--")
    ap = argparse.ArgumentParser(prog="unsticker")
    ap.add_argument("--root", default=".", help="project folder (sandboxed copy is tested)")
    ap.add_argument("--check", default=None, help="extra command that must also pass, e.g. tests")
    ap.add_argument("--max-stops", type=int, default=5)
    a = ap.parse_args(sys.argv[1:i])
    cmd = sys.argv[i + 1:]
    check = shlex.split(a.check, posix=False) if a.check else None
    return 0 if unstick(Path(a.root), cmd, check, a.max_stops) else 1


if __name__ == "__main__":
    sys.exit(main())
