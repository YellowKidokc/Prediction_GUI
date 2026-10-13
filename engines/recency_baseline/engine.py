"""Recency baseline — the second bar.

Same as frequency, but every event's vote decays with a half-life. Catches the
case where what you did last week matters more than what you did last year.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate


class RecencyBaseline(Engine):
    """Half-life-weighted most-common-value predictor."""

    name = "recency_baseline"
    target = "next_subject"

    def __init__(self, field: str = "subject", halflife_days: float = 14.0) -> None:
        self.field = field
        self.halflife = halflife_days
        self.weights: dict[str, float] = {}

    def _value(self, e: Event) -> str:
        return e.subject if self.field == "subject" else str(e.context.get(self.field, ""))

    def _w(self, ts: str) -> float:
        try:
            t = dt.datetime.fromisoformat(ts)
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            age = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400
            return math.exp(-math.log(2) * max(age, 0) / self.halflife)
        except ValueError:
            return 0.5

    def fit(self, events: list[Event]) -> None:
        w: dict[str, float] = defaultdict(float)
        for e in events:
            v = self._value(e)
            if v:
                w[v] += self._w(e.timestamp)
        self.weights = dict(w)

    def predict(self, context: dict[str, Any]) -> Prediction:
        if not self.weights:
            return self.empty("", "no history yet")
        total = sum(self.weights.values()) or 1.0
        ranked = sorted(self.weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
        cands = [Candidate(v, round(s / total, 3), f"recency-weighted share {s/total:.0%}") for v, s in ranked]
        return Prediction(engine=self.name, target=self.target, context_key="",
                          candidates=cands, markers={"halflife_days": self.halflife},
                          guidance=f"Most recent habit: {cands[0].value}")
