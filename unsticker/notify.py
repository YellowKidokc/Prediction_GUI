"""Notification plugin: unsticker events -> Prediction GUI inbox + Windows toast.

One plugin, two events:
  fixed_by_model -> incident_correction (review the fix, promote it to a fixer)
  needs_human    -> blocked_question    (nobody could solve it)
Falls back to a bare toast if the inbox/ledger can't be opened.
"""
from __future__ import annotations

import logging


def _send(template: str, title: str, message: str, subject: str, action: str,
          summary: str, payload: dict, severity: str) -> None:
    try:
        from harness.runner import Runner
        from notifications import NotificationEngine, NotificationItem
        engine = NotificationEngine(Runner().ledger)
        engine.submit(template, title, message, source="unsticker",
                      items=[NotificationItem(subject=subject, proposed_action=action,
                                              summary=summary, payload=payload)],
                      severity=severity, auto_advise=False)
    except Exception as exc:  # inbox unavailable: still beep
        logging.warning("unsticker inbox unavailable (%s); toast only", exc)
        try:
            from notifications.desktop import notify
            notify(title, message[:200])
        except Exception:
            pass


def fixed_by_model(stop: dict, summary: str, writer: str, approver: str, draft: str) -> None:
    _send("incident_correction", f"Unsticker fixed {stop['code']}",
          f"{writer} wrote it, {approver} approved, rerun passed. Promote the draft fixer?",
          subject=stop["where"], action=f"promote {draft}", summary=summary,
          payload={"stop": stop, "draft_fixer": draft, "writer": writer, "approver": approver},
          severity="normal")


def needs_human(stop: dict, attempts: int) -> None:
    _send("blocked_question", f"Unsticker stuck: {stop['code']}",
          f"{stop['why'][:140]} — {attempts} model attempts failed.",
          subject=stop["where"], action="write a fixer for this code", summary=stop["why"],
          payload={"stop": stop}, severity="high")
