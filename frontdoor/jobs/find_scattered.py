"""Job: find papers scattered across a tree -> one inbox item per family.

Read-only. No prediction engines. Steps:
 1. Walk the tree; normalize every name with the naming rule, then a looser
    key that also drops hash/chunk suffixes (_a555cf, _c1_4324e243), .bak,
    _companion, _metadata.
 2. Keep families that live in 2+ folders; skip build output (01.html,
    story.css, fisnote, __init__.py ...).
 3. Hash each copy: identical copies vs. genuinely different versions.
 4. Suggest a keeper: a copy inside a folder whose name matches the family's
    series, else the newest of the largest version.
 5. Send one approval batch: approving records your keeper choice. Nothing is
    moved, renamed or deleted.

usage: python -m frontdoor.jobs.find_scattered <spec.json>
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from frontdoor.jobs.predict_names import rules_clean  # noqa: E402

OUT = ROOT / "frontdoor" / "out"
SKIP_DIRS = {".git", ".obsidian", "__pycache__", "node_modules", ".trash", "site-packages", ".venv"}
BUILD_NOISE = re.compile(r"^(\d+t?|index|master_index|canonical_index|audio|story|init|untitled|readme|"
                         r"fisnote|slide|style|main|app|script|_index)$")


def loose_key(name: str) -> str:
    s = name
    for _ in range(2):
        s = re.sub(r"\.(md|html|htm|txt|json|bak|mp3|docx|pdf)$", "", s)
        s = re.sub(r"_(md|bak|normalized|metadata|companion|copy)$", "", s)
    s = re.sub(r"(_c\d+)?_[0-9a-f]{6,8}$", "", s)
    return s


def md5(path: str) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unreadable"


def walk(root: str, exts: set[str], match: re.Pattern | None) -> dict[str, list[str]]:
    fam: dict[str, list[str]] = collections.defaultdict(list)
    n = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fns:
            n += 1
            if exts and os.path.splitext(f)[1].lower() not in exts:
                continue
            key = loose_key(rules_clean(f))
            if BUILD_NOISE.match(key) or (match and not match.search(key)):
                continue
            fam[key].append(os.path.join(dp, f))
    print(f"[job] scanned {n} files")
    return fam


def suggest_keeper(key: str, copies: list[dict], root: str) -> tuple[dict, str]:
    words = [w for w in key.split("_") if len(w) > 2]
    series_hits = []
    for c in copies:
        parts = [rules_clean(p, True) for p in Path(c["path"]).relative_to(root).parts[:-1]]
        if any(all(w in part for w in words[:2]) for part in parts):
            series_hits.append(c)
    by_hash = collections.Counter(c["hash"] for c in copies)

    def score(c: dict) -> tuple:
        name = rules_clean(Path(c["path"]).name)
        stem = re.sub(r"\.\w+$", "", name)
        exact = stem == key                                  # not _companion / _c1_hash / .bak
        path_l = c["path"].lower()
        side = sum(t in path_l for t in WORKING_DIRS)        # pulls, imports, archives, competing
        return (c in series_hits, exact, -side, by_hash[c["hash"]], c["mtime"], c["size"])

    best = max(copies, key=score)
    s = score(best)
    reasons = (["in a folder named for this series"] if s[0] else []) + \
              (["exact paper name"] if s[1] else ["no exact-name copy; closest variant"]) + \
              (["not in a pull/import/archive folder"] if s[2] == 0 else []) + \
              [f"{by_hash[best['hash']]} identical copies of this version"]
    return best, ", ".join(reasons)


WORKING_DIRS = ("_pulls", "competing", "_imported_", "archive", "backup", "zzz", "_old", "\\old\\",
                "/old/", "intake", "dedupe", "_versions", "use_once")


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    p = spec["params"]
    root = p["folder"].replace("\\", "/")
    exts = {e if e.startswith(".") else "." + e for e in p["extensions"]}
    match = re.compile(rules_clean(p["match"], True)) if p.get("match") else None
    fam = walk(root, exts, match)
    scattered = {k: v for k, v in fam.items() if len({os.path.dirname(x) for x in v}) >= 2}
    order = sorted(scattered.items(), key=lambda kv: -len(kv[1]))[: p["limit"]]
    print(f"[job] {len(scattered)} scattered families; sending top {len(order)}")

    rows = []
    for key, paths in order:
        copies = []
        for x in paths:
            try:
                st = os.stat(x)
                copies.append({"path": x, "hash": md5(x), "size": st.st_size,
                               "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
            except OSError:
                pass
        if not copies:
            continue
        versions = len({c["hash"] for c in copies})
        tops = collections.Counter(Path(c["path"]).relative_to(root).parts[0] for c in copies)
        keeper, why = suggest_keeper(key, copies, root)
        conf = round(1 / versions, 2)  # 1 version -> safe to dedupe; many -> needs reading
        rows.append({"family": key, "keeper": keeper["path"], "why": why, "versions": versions,
                     "copies": copies, "top_folders": dict(tops.most_common()), "confidence": conf})
        print(f"  {len(copies):3} copies {versions:3} versions  {key}")

    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / f"scattered_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[job] report: {report}")

    from harness.runner import Runner
    from notifications import NotificationEngine, NotificationItem, NotificationTemplate
    items = []
    for r in rows:
        where = ", ".join(f"{k} ({v})" for k, v in list(r["top_folders"].items())[:4])
        items.append(NotificationItem(
            subject=r["family"],
            proposed_action=f"keep: {r['keeper']}",
            summary=(f"{len(r['copies'])} copies, {r['versions']} different version(s) in "
                     f"{len(r['top_folders'])} folders: {where}. Keeper because {r['why']}."),
            payload={"action_type": "pick_canonical", "risk_class": "read_only",
                     "auto_approvable": False, "confidence": r["confidence"],
                     "current_value": r["keeper"], "versions": r["versions"],
                     "copies": r["copies"], "report": str(report)}))
    if items:
        batch = NotificationEngine(Runner().ledger).submit(
            NotificationTemplate.APPROVAL_BATCH,
            f"Scattered papers: {len(items)} families" + (f" matching '{p['match']}'" if p.get("match") else ""),
            "Approving records the keeper only. Nothing is moved or deleted. Edit Final to pick a different copy.",
            f"scattered:{root}", items, auto_advise=False)
        print(f"[job] inbox batch {batch} submitted (toast sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
