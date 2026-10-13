"""mabwiser — contextual bandit (LinUCB).

Arms = the most common subjects. Context = previous subject (one-hot over the
same arms), hour of day on the clock circle, weekday one-hot. Each historical
event is a pull: the arm that actually happened gets reward 1, one other arm
(seeded random) gets reward 0 — so the bandit learns contrast, not just volume.

In shadow mode it only ranks; nothing is recommended. When it goes live, the
UCB term is the explore half: it will occasionally surface an arm it's unsure of.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from collections import Counter
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of

try:
    from mabwiser.mab import MAB, LearningPolicy
except ImportError:
    MAB = None


class BanditMabwiser(Engine):
    """LinUCB contextual bandit over the top-N subjects."""

    name = "bandit_mabwiser"
    target = "next_subject"

    def __init__(self, max_arms: int = 30, alpha: float = 1.0, max_events: int = 5000, seed: int = 7) -> None:
        self.max_arms, self.alpha, self.max_events, self.seed = max_arms, alpha, max_events, seed
        self.arms: list[str] = []
        self.mab = None
        self.prev: str | None = None
        self.n = 0

    def _ctx(self, prev: str | None, ts: str | None, hour: Any = None, dow: Any = None) -> list[float]:
        if ts:
            try:
                t = dt.datetime.fromisoformat(ts)
                hour, dow = t.hour, t.weekday()
            except ValueError:
                pass
        h = float(hour) if hour not in (None, "") else 12.0
        d = int(dow) if dow not in (None, "") else -1
        row = [1.0 if prev == a else 0.0 for a in self.arms]
        row += [math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24)]
        row += [1.0 if d == i else 0.0 for i in range(7)]
        return row

    def fit(self, events: list[Event]) -> None:
        self.mab, self.arms, self.prev, self.n = None, [], None, 0
        evs = sorted(events, key=lambda x: x.timestamp)[-self.max_events:]
        if not evs:
            return
        self.prev = evs[-1].subject
        self.arms = [s for s, _ in Counter(e.subject for e in evs).most_common(self.max_arms)]
        if MAB is None or len(self.arms) < 2:
            return
        rng = random.Random(self.seed)
        decisions, rewards, contexts, prev = [], [], [], None
        for e in evs:
            if e.subject in self.arms:
                c = self._ctx(prev, e.timestamp)
                other = rng.choice([a for a in self.arms if a != e.subject])
                decisions += [e.subject, other]; rewards += [1, 0]; contexts += [c, c]
            prev = e.subject
        if not decisions:
            return
        self.mab = MAB(arms=list(self.arms), learning_policy=LearningPolicy.LinUCB(alpha=self.alpha), seed=self.seed)
        self.mab.fit(decisions=decisions, rewards=rewards, contexts=contexts)
        self.n = len(decisions) // 2

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        if MAB is None:
            return self.empty(key, "mabwiser not available")
        if self.mab is None:
            return self.empty(key, "need 2+ distinct subjects")
        prev = context.get("prev") or self.prev
        row = self._ctx(prev, context.get("timestamp"), context.get("hour"), context.get("dow"))
        try:
            exp = self.mab.predict_expectations([row])
        except Exception as e:  # noqa: BLE001
            return self.empty(key, f"mabwiser error: {e}")
        if isinstance(exp, list):
            exp = exp[0]
        ranked = sorted(exp.items(), key=lambda kv: kv[1], reverse=True)[:5]
        pos = sum(max(v, 0.0) for _, v in ranked) or 1.0
        cands = [Candidate(str(a), round(max(v, 0.0) / pos, 3), f"UCB {v:.2f} given prev={prev}") for a, v in ranked]
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"arms": len(self.arms), "pulls": self.n, "alpha": self.alpha},
                          guidance=f"Bandit's pick: {cands[0].value}")
