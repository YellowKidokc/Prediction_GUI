"""Front door.

  python -m frontdoor "predict names for the files in \\\\server\\B_series\\01_CORE"
  python -m frontdoor --spec frontdoor/out/spec_x.json      (rerun a saved spec)
  add --yes to skip the confirmation

Request -> job spec (shown to you) -> job runs inside the unsticker loop, so if
it breaks, the ladder tries to fix it -> results land in the notification inbox.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from frontdoor.spec import translate, validate  # noqa: E402
from unsticker.ladder import unstick             # noqa: E402

JOB_MODULES = {"predict_names": "frontdoor.jobs.predict_names"}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="frontdoor")
    ap.add_argument("request", nargs="*")
    ap.add_argument("--spec")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()

    if a.spec:
        spec = validate(json.loads(Path(a.spec).read_text(encoding="utf-8")))
        spec_path = Path(a.spec)
    else:
        text = " ".join(a.request) or input("What do you want done? > ")
        spec = translate(text)
        out = ROOT / "frontdoor" / "out"
        out.mkdir(parents=True, exist_ok=True)
        spec_path = out / f"spec_{time.strftime('%Y%m%d_%H%M%S')}.json"
        spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")

    print("\nI understood:", spec.get("understood", ""))
    print(json.dumps(spec, indent=1))
    if not a.yes and input("\nRun it? [y/N] ").strip().lower() != "y":
        print("Not run. Spec saved:", spec_path)
        return 1
    cmd = [sys.executable, "-m", JOB_MODULES[spec["job"]], str(spec_path.resolve())]
    return 0 if unstick(ROOT, cmd) else 1


if __name__ == "__main__":
    sys.exit(main())
