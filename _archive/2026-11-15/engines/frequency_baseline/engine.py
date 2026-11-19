"""Frequency baseline — the bar every real engine must clear.

Predicts the next value of `field` as whatever has happened most often in the
history, ignoring context entirely. If a clever engine can't beat this, it isn't
clever.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate


class FrequencyBaseline(Engine):
    """Most-common-value predictor. No context, no recency, no excuses."""

    name = "frequency_baseline"
    target = "next_subject"
    field = "subject"          # what we count; override in engine.json via "field"

    def __init__(self, field: str = "subject") -> None:
        self.field = field
        self.counts: Counter = Counter()

    def _value(self, e: Event) -> str:
        return e.subject if self.field == "subject" else str(e.context.get(self.field, ""))

    def fit(self, events: list[Event]) -> None:
        self.counts = Counter(self._value(e) for e in events if self._value(e))

    def predict(self, context: dict[str, Any]) -> Prediction:
        if not self.counts:
            return self.empty("", "no history yet")
        total = sum(self.counts.values())
        cands = [Candidate(v, round(c / total, 3), f"{c} of {total} events")
                 for v, c in self.counts.most_common(5)]
        return Prediction(engine=self.name, target=self.target, context_key="",
                          candidates=cands, markers={"n": total},
                          guidance=f"Most common so far: {cands[0].value}")
