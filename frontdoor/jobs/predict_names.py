"""Job: every engine predicts a name for each file -> one approval batch.

Read-only on the source folder. Steps:
 1. Teach the 9 harness engines the series layout of train_root
    (event: subject = series folder, context words = filename words).
 2. For each target file, the engines vote which series it belongs to.
 3. Name proposers each propose a filename (rules, Jev, DeepSeek, David-OS planner).
 4. Votes are combined; the plan goes to the inbox as an approval batch (+ toast).

usage: python -m frontdoor.jobs.predict_names <spec.json>
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness.contract import Event          # noqa: E402
from harness.runner import Runner           # noqa: E402
from unsticker.llm import extract_json, tiers  # noqa: E402

OUT = ROOT / "frontdoor" / "out"
SKIP_DIRS = {".git", ".obsidian", "__pycache__", "node_modules", ".trash"}


# ---------- 1. engines learn the series layout ------------------------------
def train_events(train_root: Path, cap: int = 3000) -> list[Event]:
    events = []
    for series_dir in sorted(p for p in train_root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
        n = 0
        for f in series_dir.rglob("*"):
            if f.is_file() and not any(part in SKIP_DIRS for part in f.parts):
                events.append(Event(subject=series_dir.name, action="filed", source="frontdoor",
                                    context={"words": f.stem, "folder_class": f.suffix.lower(),
                                             "paper": str(f)}))
                n += 1
                if n >= 150 or len(events) >= cap:
                    break
        if len(events) >= cap:
            break
    return events


def engine_votes(runner: Runner, f: Path) -> list[dict]:
    preds = runner.shadow({"words": f.stem, "folder_class": f.suffix.lower(), "paper": str(f)})
    out = []
    for p in preds:
        top = p.top
        out.append({"engine": p.engine, "value": top.value if top else None,
                    "confidence": round(top.confidence, 3) if top else 0.0,
                    "reason": (top.reason if top else p.guidance)[:120]})
    return out


# ---------- 3. name proposers ------------------------------------------------
NAMING_RULE = ("Normalize to the series/topic name only: lowercase; spaces and dashes become "
               "underscores; fix spelling (e.g. THEOPYHISCS -> theophysics); remove ALL leading "
               "order numbers and codes (e.g. '04_', 'A0_', 'ONES.06.', 'v2', 'B_'); remove stray "
               "numbers, dates, versions and words like copy/backup/final; keep the extension; "
               "for folders there is no extension. Short/long codes are added later, not now.")

PREFIX = re.compile(r"^(?:\d+[a-z]?|[a-z]\d+|ones|v\d+(?:\.\d+)*|[a-z])(?=[._\-\s])[._\-\s]+", re.I)
NOISE = re.compile(r"(?:^|_)(?:\d+(?:[.\-]\d+)*|v\d+(?:\.\d+)*|copy|backup|final|draft|new)(?=_|$)", re.I)


def rules_clean(name: str, is_dir: bool = False) -> str:
    """Deterministic normalizer (no spell-correct; the models do that)."""
    stem, ext = (name, "") if is_dir else (Path(name).stem, Path(name).suffix.lower())
    s = stem.strip()
    while True:
        t = PREFIX.sub("", s, count=1)
        if t == s or not t:
            break
        s = t
    s = re.sub(r"\(.*?\)|[^\w\s\-.+]", " ", s)
    s = re.sub(r"[\s\-.]+", "_", s.lower())
    s = NOISE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or stem.lower()) + ext


def llm_batch(model, files: list[Path], series_hint: dict[str, str], rule: str,
              chunk: int = 10) -> dict[str, str]:
    """Cheap models drop big batches, so ask in chunks of 10."""
    out: dict[str, str] = {}
    for i in range(0, len(files), chunk):
        out.update(_llm_chunk(model, files[i:i + chunk], series_hint, rule))
    return out


def _llm_chunk(model, files: list[Path], series_hint: dict[str, str], rule: str) -> dict[str, str]:
    # The engines' series vote is NOT shown to the models: untrained engines all
    # vote the biggest folder, and cheap models copy the hint. It stays in the record.
    rows = [{"current": f.name, "folder": f.parent.name} for f in files]
    sys_prompt = ("You normalize file and folder names. Rule: " + NAMING_RULE +
                  ' Reply ONLY JSON: {"names": {"<current>": "<proposed>"}}')
    user = (f"Extra instructions from the user: {rule or '(none)'}\n"
            + json.dumps(rows, ensure_ascii=False, indent=1))
    try:
        data = extract_json(model.chat(sys_prompt, user, temperature=0.1, max_tokens=4000))
        return {k: v for k, v in data.get("names", {}).items() if isinstance(v, str) and v.strip()}
    except Exception as exc:
        print(f"  [{model.name}] abstained: {exc}")
        return {}


def davidos_planner(_f: Path) -> tuple[str | None, str]:
    # David-OS rename_planner needs a fully classified FileRecord (config, tagger,
    # preference engine). Not wired yet: it abstains and says why.
    return None, "David-OS planner needs a classified FileRecord; not wired for raw folders yet"


# ---------- 4. combine -------------------------------------------------------
def combine(current: str, proposals: dict[str, str | None]) -> tuple[str, float, str]:
    norm = {k: v for k, v in proposals.items() if v}
    if not norm:
        return current, 0.0, "no proposer answered"
    counts = Counter(v.lower() for v in norm.values())
    best_l, n = counts.most_common(1)[0]
    best = next(v for v in norm.values() if v.lower() == best_l)
    agree = [k for k, v in norm.items() if v.lower() == best_l]
    if n == 1:  # nobody agrees: trust the strongest proposer that answered
        for k in ("deepseek", "jev", "rules"):
            if norm.get(k):
                best, agree = norm[k], [k]
                break
    conf = round(len(agree) / max(len(norm), 1), 2)
    return best, conf, f"agree: {', '.join(agree)} of {len(norm)} proposers"


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    p = spec["params"]
    folder, train_root = Path(p["folder"]), Path(p["train_root"])
    glob = folder.rglob if p["recursive"] else folder.glob
    want_dirs = p.get("kind") == "folders"
    files = sorted(f for f in glob(p["pattern"])
                   if (f.is_dir() if want_dirs else f.is_file()) and f.name not in SKIP_DIRS
                   and not f.name.startswith("."))[: p["limit"]]
    if not files:
        raise SystemExit(f"no files match {p['pattern']} in {folder}")
    print(f"[job] {len(files)} files in {folder}")

    runner = Runner(db_path=ROOT / "data" / "frontdoor_harness.db", context_keys=("folder_class",))
    events = train_events(train_root)
    runner.ingest(events)
    print(f"[job] engines trained on {len(events)} filed examples from {train_root}")

    votes = {f.name: engine_votes(runner, f) for f in files}
    series_hint = {}
    for name, vs in votes.items():
        c = Counter(v["value"] for v in vs if v["value"])
        series_hint[name] = c.most_common(1)[0][0] if c else ""

    T = tiers()
    jev = llm_batch(T["jev"], files, series_hint, p["naming_rule"])
    ds = llm_batch(T["deepseek"], files, series_hint, p["naming_rule"])

    rows = []
    for f in files:
        dname, dwhy = davidos_planner(f)
        props = {"rules": rules_clean(f.name, f.is_dir()), "jev": jev.get(f.name),
                 "deepseek": ds.get(f.name), "davidos_planner": dname}
        best, conf, why = combine(f.name, props)
        preds = [{"engine": k, "value": v, "confidence": None} for k, v in props.items()]
        preds += [{"engine": f"series:{v['engine']}", "value": v["value"],
                   "confidence": v["confidence"]} for v in votes[f.name]]
        rows.append({"current_path": str(f), "proposed_name": best, "confidence": conf,
                     "reason": f"{why}; engines' series vote: {series_hint[f.name] or 'none'}",
                     "engine_predictions": preds, "prediction_producer": "frontdoor.predict_names"})

    seen = Counter(r["proposed_name"].lower() for r in rows)
    for r in rows:
        if seen[r["proposed_name"].lower()] > 1:
            r["confidence"] = min(r["confidence"], 0.3)
            r["reason"] = f"COLLISION: {seen[r['proposed_name'].lower()]} items -> same name (merge?); " + r["reason"]

    OUT.mkdir(parents=True, exist_ok=True)
    plan = OUT / f"name_plan_{time.strftime('%Y%m%d_%H%M%S')}.json"
    plan.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    changed = sum(1 for r in rows if Path(r["current_path"]).name != r["proposed_name"])
    print(f"[job] plan written: {plan}  ({changed} of {len(rows)} would change)")

    from notifications import NotificationEngine
    from notifications.adapters import naming
    batch = naming.submit(NotificationEngine(Runner().ledger), plan)
    print(f"[job] inbox batch {batch} submitted (toast sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
