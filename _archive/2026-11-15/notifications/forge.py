"""Bounded AI adviser through Forge. Advice is recorded; it never changes status."""
from __future__ import annotations

import json
import os
import urllib.request


SYSTEM = """You advise on a review inbox. Mistakes are acceptable; confident invention is not.
Say when evidence is insufficient. Return concise JSON with keys summary, per_item, confidence,
and questions. You may recommend approve, hold, or reject, but you cannot authorize changes."""


def advise(batch: dict, items: list[dict], timeout: int = 45) -> tuple[str, float | None]:
    base = os.environ.get("FORGE_URL", "http://127.0.0.1:8790").rstrip("/")
    model = os.environ.get("FORGE_MODEL", "auto")
    payload = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({"batch": batch, "items": items})},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(base + "/v1/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = body["choices"][0]["message"]["content"]
    confidence = None
    try:
        parsed = json.loads(text)
        confidence = float(parsed["confidence"]) if "confidence" in parsed else None
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return text, confidence
