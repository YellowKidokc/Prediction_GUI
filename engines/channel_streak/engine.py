"""Streak baseline — "three on a channel, pull the channel."

If the last `streak` events all share the same value of `field`, predict that
value again. Otherwise say nothing. Abstaining is allowed: an empty prediction
is never scored, so this engine's hit-rate is its hit-rate *when it speaks*.

field defaults to "channel", which Chrome history alone doesn't carry — this
engine is silent until the yt worker writes channel into event context.
"""
from __future__ import annotations

from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of


class ChannelStreak(Engine):
    """N-in-a-row on one value of a context field -> predict it continues."""

    name = "channel_streak"
    target = "next_channel"

    def __init__(self, field: str = "channel", streak: int = 3) -> None:
        self.field, self.streak = field, streak
        self.tail: list[str] = []

    def _value(self, e: Event) -> str:
        return e.subject if self.field == "subject" else str(e.context.get(self.field, "") or "")

    def fit(self, events: list[Event]) -> None:
        self.tail = [self._value(e) for e in sorted(events, key=lambda x: x.timestamp)[-self.streak:]]

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        recent = list(context.get(f"recent_{self.field}") or self.tail)[-self.streak:]
        if len(recent) < self.streak or not recent[-1]:
            return self.empty(key, f"no {self.field} in recent events")
        if len(set(recent)) != 1:
            return self.empty(key, f"no {self.streak}-streak on {self.field}")
        v = recent[-1]
        return Prediction(engine=self.name, target=self.target, context_key=key,
                          candidates=[Candidate(v, 0.6, f"last {self.streak} events all {self.field}={v}")],
                          markers={"streak": self.streak, "field": self.field},
                          guidance=f"On a {self.field} streak: queue more from {v}")
