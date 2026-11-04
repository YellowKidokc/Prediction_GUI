"""Dependency-free validation for the stable API envelope."""
from __future__ import annotations

ALLOWED_DECISIONS = {"approved", "held", "rejected", "answered"}
ALLOWED_RISK = {"read_only", "additive", "mutation", "canon_authority"}


def notification(data: dict) -> None:
    for key in ("template", "title", "source", "items"):
        if not data.get(key): raise ValueError(f"missing {key}")
    if not isinstance(data["items"], list): raise ValueError("items must be a list")
    for number, item in enumerate(data["items"], 1):
        if not item.get("subject") or not item.get("proposed_action"):
            raise ValueError(f"item {number}: subject and proposed_action are required")
        confidence = item.get("confidence")
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise ValueError(f"item {number}: confidence must be 0..1")
        if item.get("risk_class", "mutation") not in ALLOWED_RISK:
            raise ValueError(f"item {number}: invalid risk_class")


def decision(data: dict) -> None:
    if data.get("decision") not in ALLOWED_DECISIONS: raise ValueError("invalid decision")
    if not isinstance(data.get("item_ids"), list) or not data["item_ids"]:
        raise ValueError("item_ids must be a non-empty list")
