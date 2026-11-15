"""Prediction_GUI harness contract — the three things every engine agrees on.

Event      : anything that happened (a watch, a file move, a command, a click).
Prediction : what an engine thinks will happen next, with confidence and why.
Engine     : the plug.  Subclass it, drop the folder under engines/, run intake.

No ML libraries. No hidden state. If it can't be explained, it can't be scored.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Event:
    """One observation. `subject` is the thing acted on, `action` what happened,
    `context` is free-form (channel, folder, hour, whatever the adapter knows)."""
    subject: str
    action: str
    context: dict[str, Any] = field(default_factory=dict)
    source: str = "manual"
    timestamp: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class Candidate:
    value: str
    confidence: float          # 0..1
    reason: str = ""


@dataclass
class Prediction:
    """What an engine says before the outcome is known."""
    engine: str
    target: str                       # what is being predicted, e.g. "next_channel"
    context_key: str                  # the situation this prediction applies to
    candidates: list[Candidate]       # best first
    markers: dict[str, Any] = field(default_factory=dict)   # engine-specific extras
    guidance: str = ""                # one line a human can act on
    timestamp: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["top"] = asdict(self.top) if self.top else None
        return d


class Engine:
    """Subclass this. Keep it dumb and explainable."""

    name: str = "unnamed"
    target: str = "next_subject"      # what this engine predicts
    version: str = "0.1"

    def fit(self, events: list[Event]) -> None:
        """Rebuild internal state from the full event history. Called on load and
        after every batch of new events. Must be idempotent."""
        raise NotImplementedError

    def predict(self, context: dict[str, Any]) -> Prediction:
        """Return a Prediction for the given situation. Never raise — return an
        empty candidate list if there is nothing to say."""
        raise NotImplementedError

    def explain(self) -> str:
        """One paragraph: what signals this engine uses."""
        return self.__doc__ or "no description"

    def empty(self, context_key: str, why: str = "insufficient data") -> Prediction:
        return Prediction(engine=self.name, target=self.target, context_key=context_key,
                          candidates=[], guidance=why)


def context_key_of(context: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Stable string for 'the situation' so predictions can be scored later."""
    return "|".join(f"{k}={context.get(k, '')}" for k in keys)
