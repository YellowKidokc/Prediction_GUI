"""Human-editable template catalog; adding a JSON entry requires no code change."""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).with_name("templates.json")


def load() -> dict[str, dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def validate(name: str) -> dict:
    catalog = load()
    if name not in catalog:
        raise ValueError(f"unknown notification template {name!r}; add it to {PATH}")
    return catalog[name]
