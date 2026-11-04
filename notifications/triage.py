"""Uniform confidence bands. Confidence reduces review load, never expands authority."""
from __future__ import annotations


LOW = 0.60
HIGH = 0.90
SAFE_RISK_CLASSES = {"read_only", "additive"}


def band(confidence) -> str:
    if confidence is None: return "unknown"
    value = float(confidence)
    if value >= HIGH: return "high"
    if value >= LOW: return "mixed"
    return "low"


def may_auto_approve(payload: dict) -> bool:
    """Both declarations are required. Confidence alone is never authority."""
    return (band(payload.get("confidence")) == "high"
            and payload.get("risk_class") in SAFE_RISK_CLASSES
            and payload.get("auto_approvable") is True)
