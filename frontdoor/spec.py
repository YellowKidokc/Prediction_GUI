"""Front door: plain-English request -> validated job spec.

You type what you want. A model (Jev first, DeepSeek if Jev's answer doesn't
validate) fills in the job template. The spec is shown to you before anything
runs. Only job types listed in JOB_TYPES can run; nothing else is possible.
"""
from __future__ import annotations

import json
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
    last_err = ""
    for model in (T["jev"], T["deepseek"]):
        try:
            spec = extract_json(model.chat(sys_prompt, request, temperature=0.0, max_tokens=800))
            spec["_translated_by"] = model.name
            return validate(spec)
        except Exception as exc:
            last_err = f"{model.name}: {exc}"
    raise ValueError(f"could not turn the request into a job spec ({last_err})")


def validate(spec: dict) -> dict:
    job = spec.get("job")
    if job == "none":
        raise ValueError(f"request doesn't fit a job: {spec.get('missing') or spec.get('understood')}")
    if job not in JOB_TYPES:
        raise ValueError(f"unknown job type {job!r}")
    p = spec.setdefault("params", {})
    if job == "predict_names":
        folder = Path(str(p.get("folder", "")))
        if not folder.is_dir():
            raise ValueError(f"folder not found: {folder}")
        p["folder"] = str(folder)
        p["kind"] = "folders" if str(p.get("kind", "")).lower().startswith("folder") else "files"
        p["pattern"] = p.get("pattern") or ("*" if p["kind"] == "folders" else "*.md")
        p["recursive"] = str(p.get("recursive", "false")).lower() == "true"
        p["limit"] = max(1, min(int(p.get("limit") or 25), 200))
        p["naming_rule"] = p.get("naming_rule") or ""
        p["train_root"] = str(p.get("train_root") or (folder if p["kind"] == "folders" else folder.parent))
    return spec
