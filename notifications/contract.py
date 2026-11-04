"""Stable contract shared by prediction engines, pipelines, and the desktop inbox."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from harness.contract import utc_now


class NotificationTemplate:
    """Names of the starter templates. Custom template names are equally valid."""

    APPROVAL_BATCH = "approval_batch"
    BLOCKED_QUESTION = "blocked_question"
    INCIDENT_CORRECTION = "incident_correction"


class Decision:
    APPROVED = "approved"
    HELD = "held"
    REJECTED = "rejected"
    ANSWERED = "answered"


@dataclass
class NotificationItem:
    subject: str
    proposed_action: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class NotificationBatch:
    template: str
    title: str
    message: str
    source: str
    items: list[NotificationItem]
    severity: str = "normal"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=utc_now)
