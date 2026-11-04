"""Match series names against David's authoritative multimedia registry workbook."""
from __future__ import annotations

import os, re
from difflib import SequenceMatcher
from pathlib import Path
from notifications.contract import NotificationItem, NotificationTemplate

DEFAULT_FOLDER = Path(r"C:\Users\David\Documents\faiththruphysics.com\40_MEDIA\80_REGISTRY")

def locate() -> Path:
    explicit = os.environ.get("THEOPHYSICS_SERIES_REGISTRY")
    if explicit and Path(explicit).is_file(): return Path(explicit)
    choices = list(DEFAULT_FOLDER.glob("LIBR - Series Multimedia Master - *.xlsx"))
    if not choices: raise FileNotFoundError("series registry workbook not found; set THEOPHYSICS_SERIES_REGISTRY")
    return max(choices, key=lambda p: p.stat().st_mtime)

def records(path: str | Path | None = None) -> list[dict]:
    try: import openpyxl
    except ImportError as exc: raise RuntimeError("series workbook matching requires openpyxl") from exc
    workbook = openpyxl.load_workbook(path or locate(), read_only=False, data_only=True)
    sheet = workbook["Series Registry"]
    headers = [str(c.value or "").strip() for c in sheet[1]]
    return [dict(zip(headers, row)) for row in sheet.iter_rows(min_row=2, values_only=True) if row[0]]

def _norm(value: str) -> str: return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))

def _names(row: dict) -> list[str]:
    return [str(row.get("Code") or ""), str(row.get("Full series name") or ""),
            *re.split(r"[;|]", str(row.get("Older aliases") or ""))]

def propose_code(name: str, used: set[str]) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name.upper()) if w not in {"THE","A","AN","OF","TO","AND","FOR","IN"}]
    if len(words) >= 3: base = "".join(w[0] for w in words[:4])
    elif len(words) == 2: base = (words[0][:2] + words[1][:2])[:4]
    else: base = words[0][:4] if words else "NEW"
    if len(base) < 3: base = (base + "XXX")[:3]
    candidate, number = base, 2
    while candidate in used: candidate, number = (base[:3] + str(number))[:4], number + 1
    return candidate

def classify(name: str, registry: list[dict] | None = None) -> dict:
    registry = registry or records(); query = _norm(name)
    used = {str(r.get("Code") or "").upper() for r in registry}; scored = []
    for row in registry:
        candidates = [_norm(v) for v in _names(row) if _norm(v)]
        exact = query in candidates
        score = 1.0 if exact else max((SequenceMatcher(None, query, c).ratio() for c in candidates), default=0)
        scored.append((score, exact, row))
    score, exact, row = max(scored, key=lambda x: x[0])
    if exact or score >= .88:
        return {"status":"identified", "code":row["Code"], "series_name":row["Full series name"],
                "confidence":1.0 if exact else round(score,3), "match":"exact" if exact else "close", "lifecycle_code":"PD"}
    return {"status":"new_code_proposed", "code":propose_code(name, used), "series_name":name,
            "confidence":round(max(.5, 1-score),3), "match":"none", "nearest_code":row.get("Code"),
            "nearest_name":row.get("Full series name"), "lifecycle_code":"PD"}

def submit(engine, names: list[str], desktop: bool = True) -> str:
    registry = records(); items = []
    for name in names:
        result = classify(name, registry)
        items.append(NotificationItem(name, result["code"], f"{result['status']}: {result['series_name']}",
            {"current_value":name, "confidence":result["confidence"], "risk_class":"canon_authority",
             "auto_approvable":False, "sidecar_lifecycle":"PD", "series_match":result}))
    return engine.submit(NotificationTemplate.APPROVAL_BATCH, "Series classification review",
        "Workbook matches are identified; unmatched names receive a proposed 3-4 character code.",
        f"series-registry:{locate()}", items, desktop=desktop)
