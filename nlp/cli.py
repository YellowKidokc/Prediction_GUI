"""python -m nlp.cli plan  <name> <folder> "<goal>"
   python -m nlp.cli run   <name> [--limit N]
   python -m nlp.cli revise <name> "<what to change>"
   python -m nlp.cli lock  <name> [version]      / unlock <name>
   python -m nlp.cli show  <name>                / list
   python -m nlp.cli steps                       (catalog + what's installed)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nlp.pipeline import Pipeline  # noqa: E402
from nlp import steps  # noqa: E402


def main(a: list[str]) -> int:
    if not a:
        print(__doc__); return 1
    cmd = a[0]
    if cmd == "steps":
        for s in steps.describe():
            print(f"{'✓' if s['available'] else '✗'} {s['step']:<20} {s['requires']:<8} {s['description']}")
    elif cmd == "list":
        for p in Pipeline.all():
            print(p.data["name"], f"v{len(p.data['versions'])}", "locked" if p.data["locked"] else "draft", p.data["folder"])
    elif cmd == "plan":
        v = Pipeline(a[1]).plan(a[2], a[3] if len(a) > 3 else "understand this folder")
        print(json.dumps(v, indent=2))
    elif cmd == "revise":
        print(json.dumps(Pipeline(a[1]).revise(a[2]), indent=2))
    elif cmd == "run":
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        d = Pipeline(a[1]).run(limit, progress=print); print((d / "report.md").read_text("utf-8")[:3000])
    elif cmd == "lock":
        print("locked v", Pipeline(a[1]).lock(int(a[2]) if len(a) > 2 else None))
    elif cmd == "unlock":
        Pipeline(a[1]).unlock(); print("unlocked")
    elif cmd == "show":
        print(json.dumps(Pipeline(a[1]).data, indent=2))
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (RuntimeError, IndexError, FileNotFoundError) as e:
        print(f"error: {e}"); raise SystemExit(2)
