"""Universal Atom API Contract v1.0 -> human review row.

Canonical source: Faith-through-physics-atoms/_template/schemas/atom-api-contract.json
"""
from __future__ import annotations

from notifications.contract import NotificationItem


def item_from_atom(payload: dict) -> NotificationItem:
    if payload.get("schema_version") != "atom-universal/1.0": raise ValueError("expected schema_version atom-universal/1.0")
    atom = payload.get("atom") or {}
    for key in ("id", "type", "title", "claim"):
        if not atom.get(key): raise ValueError(f"atom.{key} is required")
    identity, atom_type = payload.get("identity") or {}, atom["type"]
    if atom_type == "lean":
        lean = atom.get("lean_block") or {}
        proposal = f"review Lean receipt: {lean.get('compile_status', 'pending')}"
        reason = f"{lean.get('theorem_name', atom['title'])}; zero_sorry={lean.get('zero_sorry', 'unknown')}; axioms={', '.join(lean.get('axioms_used') or []) or 'unrecorded'}"
        risk = "additive"
    else:
        commitment, register = atom.get("commitment", "Working"), atom.get("register", "")
        proposal = f"review standing: {commitment}{' / ' + register if register else ''}"
        reason = atom.get("role") or atom.get("status") or "Atom standing review"
        risk = "canon_authority" if commitment.lower() == "canon" or register == "canon" else "additive"
    return NotificationItem(atom["id"], proposal, reason, {
        "current_value": identity.get("publication_state") or atom.get("commitment") or atom.get("status", ""),
        "confidence": (payload.get("nabla") or {}).get("confidence"), "risk_class": risk,
        "auto_approvable": False, "atom_type": atom_type, "source_hash": identity.get("source_hash"),
        "evidence": {"receipts": payload.get("receipts", {}), "alerts": payload.get("alerts", []), "lean_block": atom.get("lean_block")},
        "atom_payload": payload})
