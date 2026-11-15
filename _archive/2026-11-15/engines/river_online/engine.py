"""river — online learning. Learns one event at a time, never needs a retrain.

Treats "next subject" as a classification problem: features are the previous
subject + hour + weekday (+ anything else in context that's a short string or
number); label is the subject that followed. Multinomial Naive Bayes keeps it
explainable; swap the model line for a tree or logistic regression to compare.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of

try:
    from river import naive_bayes
except ImportError:
    naive_bayes = None

SKIP = {"title", "url"}   # long strings: not features


class RiverOnline(Engine):
    """Online Naive Bayes: P(next subject | previous subject, hour, weekday, context)."""

    name = "river_online"
    target = "next_subject"

    def __init__(self) -> None:
        self.model = naive_bayes.MultinomialNB() if naive_bayes else None
        self.seen = 0
        self.last_feats: dict[str, Any] = {}

    @staticmethod
    def _feats(prev: str | None, e_ctx: dict[str, Any], ts: str | None) -> dict[str, Any]:
        f: dict[str, Any] = {"prev=" + (prev or "<start>"): 1}
        if ts:
            try:
                t = dt.datetime.fromisoformat(ts)
                f[f"hour={t.hour}"] = 1; f[f"dow={t.weekday()}"] = 1
            except ValueError:
                pass
        for k, v in e_ctx.items():
            if k in SKIP or v in (None, ""):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                f[f"{k}={int(v)}"] = 1
            elif isinstance(v, str) and len(v) <= 40:
                f[f"{k}={v}"] = 1
        return f

    def fit(self, events: list[Event]) -> None:
        self.model = naive_bayes.MultinomialNB() if naive_bayes else None
        self.seen, self.last_feats = 0, {}
        if self.model is None:
            return
        prev = None
        for e in sorted(events, key=lambda x: x.timestamp):
            x = self._feats(prev, e.context, e.timestamp)
            self.model.learn_one(x, e.subject)
            prev, self.seen = e.subject, self.seen + 1
        self.last_feats = {"prev": prev}

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        if self.model is None:
            return self.empty(key, "river not available")
        if self.seen < 5:
            return self.empty(key, f"only {self.seen} events")
        prev = context.get("prev") or self.last_feats.get("prev")
        x = self._feats(prev, context, context.get("timestamp"))
        try:
            probs = self.model.predict_proba_one(x)
        except Exception as e:  # noqa: BLE001
            return self.empty(key, f"river error: {e}")
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:5]
        cands = [Candidate(str(v), round(float(p), 3), f"NB posterior given prev={prev}") for v, p in ranked if p > 0]
        if not cands:
            return self.empty(key, "no posterior mass")
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"seen": self.seen, "features": len(x)},
                          guidance=f"Given {prev} at this time: {cands[0].value}")
