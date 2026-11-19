"""Front door: plain-English request -> validated job spec.

You type what you want. A model (Jev first, DeepSeek if Jev's answer doesn't
validate) fills in the job template. The spec is shown to you before anything
runs. Only job types listed in JOB_TYPES can run; nothing else is possible.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from unsticker.llm import extract_json, tiers

JOB_TYPES = {
    "predict_names": {
        "describe": "Read-only. Every engine/proposer predicts a better filename for each file "
                    "in a folder; results arrive as one approval batch in the notification inbox. "
                    "Nothing is renamed.",
        "fields": {
            "folder": "absolute path of the folder whose files get name predictions (required)",
            "kind": "'files' or 'folders' (series are usually folders), default files",
            "pattern": "glob for which items, default *.md for files, * for folders",
            "recursive": "true/false, default false",
            "limit": "max files this run, default 25 (keeps API cost bounded)",
            "naming_rule": "the user's naming instructions in their words, or empty",
            "train_root": "folder whose existing layout teaches the engines the series, "
                          "default = parent of folder",
        },
    },
    "find_scattered": {
        "describe": "Read-only, no prediction engines. Finds the same paper scattered across many "
                    "folders (matching by normalized name), checks which copies are identical vs. "
                    "different versions, suggests one keeper per paper, and sends the families to "
                    "the inbox. Nothing is moved or deleted.",
        "fields": {
            "folder": "absolute path of the tree to search (required)",
            "match": "only papers whose name contains these words, e.g. 'God Is'; empty = all",
            "extensions": "list of file types to consider, default [\".md\"]",
            "limit": "max families to send, default 40",
        },
    },
}

SYSTEM = """You turn a user's plain-English request into ONE job spec for a local automation system.
Allowed job types and their fields:
{types}
Reply with ONLY JSON: {{"job": "<type>", "params": {{...}}, "understood": "one sentence restating the request"}}
If the request does not fit any job type, reply {{"job": "none", "understood": "...", "missing": "what is unclear"}}.
Use Windows paths exactly as the user wrote them. Do not invent folders."""


def translate(request: str) -> dict:
    sys_prompt = SYSTEM.format(types=json.dumps(JOB_TYPES, indent=1))
    T = tiers()
    errors = []
    for model in (T["jev"], T["deepseek"]):
        try:
            spec = extract_json(model.chat(sys_prompt, request, temperature=0.0, max_tokens=800))
            spec["_translated_by"] = model.name
            return validate(spec)
        except Exception as exc:
            errors.append(f"{model.name}: {exc}")
    raise ValueError("could not turn the request into a job spec:\n- " + "\n- ".join(errors))


def fix_path(raw: str) -> Path:
    """Models often double backslashes in Windows/UNC paths. Collapse them,
    keeping the leading \\\\ of a network path."""
    s = str(raw).strip().strip('"')
    unc = s.startswith("\\\\")
    s = re.sub(r"\\{2,}", r"\\", s)
    if unc:
        s = "\\" + s if not s.startswith("\\\\") else s
    return Path(s)


def validate(spec: dict) -> dict:
    job = spec.get("job")
    if job == "none":
        raise ValueError(f"request doesn't fit a job: {spec.get('missing') or spec.get('understood')}")
    if job not in JOB_TYPES:
        raise ValueError(f"unknown job type {job!r}")
    p = spec.setdefault("params", {})
    if job == "predict_names":
        folder = fix_path(p.get("folder", ""))
        if not folder.is_dir():
            raise ValueError(f"folder not found: {folder}")
        p["folder"] = str(folder)
        p["kind"] = "folders" if str(p.get("kind", "")).lower().startswith("folder") else "files"
        p["pattern"] = p.get("pattern") or ("*" if p["kind"] == "folders" else "*.md")
        p["recursive"] = str(p.get("recursive", "false")).lower() == "true"
        p["limit"] = max(1, min(int(p.get("limit") or 25), 200))
        p["naming_rule"] = p.get("naming_rule") or ""
        p["train_root"] = str(p.get("train_root") or (folder if p["kind"] == "folders" else folder.parent))
    elif job == "find_scattered":
        folder = fix_path(p.get("folder", ""))
        if not folder.is_dir():
            raise ValueError(f"folder not found: {folder}")
        p["folder"] = str(folder)
        p["match"] = str(p.get("match") or "")
        ext = p.get("extensions") or [".md"]
        p["extensions"] = [ext] if isinstance(ext, str) else list(ext)
        p["limit"] = max(1, min(int(p.get("limit") or 40), 300))
    return spec
