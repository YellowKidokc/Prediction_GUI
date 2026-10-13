"""Compact Prediction Tree (Gueniche, Fournier-Viger, Tseng 2013) via the `cpt` package.

Lossless sequence predictor: stores every past sequence in a prefix tree and
predicts the next item by finding sequences similar to the recent window. No
training loop, no hyper-tuning worth the name, strong on long histories.

Sequence unit = the event subject (video id, channel, file, command) in time order.
Context should carry "recent": the last k subjects, oldest first. If absent, the
engine uses the tail of the history it was fit on.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of

try:
    from cpt.cpt import Cpt
except ImportError:  # keep intake happy even if the venv isn't active
    Cpt = None


class CPTEngine(Engine):
    """Compact Prediction Tree over subject sequences; predicts from the last k subjects."""

    name = "cpt_sequence"
    target = "next_subject"

    def __init__(self, window: int = 5, split_on_gap_hours: float = 6.0) -> None:
        self.window = window
        self.gap = split_on_gap_hours
        self.model = None
        self.tail: list[str] = []
        self.n_seq = 0

    def _sessions(self, events: list[Event]) -> list[list[str]]:
        """Split the time-ordered history into sessions at gaps > self.gap hours."""
        out: list[list[str]] = []
        cur: list[str] = []
        last: dt.datetime | None = None
        for e in sorted(events, key=lambda x: x.timestamp):
            try:
                t = dt.datetime.fromisoformat(e.timestamp)
            except ValueError:
                t = last
            if last is not None and t is not None and (t - last).total_seconds() > self.gap * 3600 and cur:
                out.append(cur); cur = []
            cur.append(e.subject)
            last = t
        if cur:
            out.append(cur)
        return [s for s in out if len(s) >= 2]

    def fit(self, events: list[Event]) -> None:
        self.model, self.n_seq, self.tail = None, 0, [e.subject for e in events[-self.window:]]
        if Cpt is None or not events:
            return
        seqs = self._sessions(events)
        if not seqs:
            return
        m = Cpt()
        m.fit(seqs)
        self.model, self.n_seq = m, len(seqs)

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        if self.model is None:
            return self.empty(key, "cpt not available or no sessions yet")
        recent = list(context.get("recent") or self.tail)[-self.window:]
        if not recent:
            return self.empty(key, "no recent sequence")
        try:
            preds = self.model.predict_k([recent], k=5)[0]
        except Exception as e:  # noqa: BLE001
            return self.empty(key, f"cpt error: {e}")
        cands = [Candidate(str(v), round(1.0 / (i + 1), 3), f"rank {i+1} from similar sequences")
                 for i, v in enumerate(preds) if v]
        if not cands:
            return self.empty(key, "no similar sequence found")
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"sessions": self.n_seq, "recent": recent},
                          guidance=f"After {recent[-1]}, you usually go to {cands[0].value}")
