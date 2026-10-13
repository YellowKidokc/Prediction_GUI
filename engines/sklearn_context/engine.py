"""scikit-learn — the boring control. Batch logistic regression over the same
features river uses (previous subject, hour, weekday, short context values).

If this ties river_online, online learning bought nothing. If it beats the
baselines, context matters. Either answer is worth having.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of

try:
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
except ImportError:
    LogisticRegression = None

SKIP = {"title", "url", "preview"}   # long strings: not features


class SklearnContext(Engine):
    """Logistic regression: P(next subject | previous subject, hour, weekday, context)."""

    name = "sklearn_context"
    target = "next_subject"

    def __init__(self, max_events: int = 20000) -> None:
        self.max_events = max_events
        self.vec = None
        self.model = None
        self.prev: str | None = None
        self.n = 0

    @staticmethod
    def _feats(prev: str | None, ctx: dict[str, Any], ts: str | None) -> dict[str, Any]:
        f: dict[str, Any] = {"prev=" + (prev or "<start>"): 1}
        if ts:
            try:
                t = dt.datetime.fromisoformat(ts)
                f[f"hour={t.hour}"] = 1; f[f"dow={t.weekday()}"] = 1
            except ValueError:
                pass
        for k, v in ctx.items():
            if k in SKIP or k.startswith("_") or v in (None, ""):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                f[f"{k}={int(v)}"] = 1
            elif isinstance(v, str) and len(v) <= 40:
                f[f"{k}={v}"] = 1
        return f

    def fit(self, events: list[Event]) -> None:
        self.vec, self.model, self.prev, self.n = None, None, None, 0
        evs = sorted(events, key=lambda x: x.timestamp)[-self.max_events:]
        if LogisticRegression is None or not evs:
            return
        X, y, prev = [], [], None
        for e in evs:
            X.append(self._feats(prev, e.context, e.timestamp)); y.append(e.subject)
            prev = e.subject
        self.prev, self.n = prev, len(y)
        if len(set(y)) < 2:
            return              # one class: nothing to discriminate, baselines cover it
        self.vec = DictVectorizer()
        self.model = LogisticRegression(max_iter=500)
        self.model.fit(self.vec.fit_transform(X), y)

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        if LogisticRegression is None:
            return self.empty(key, "scikit-learn not available")
        if self.model is None:
            return self.empty(key, f"need 2+ distinct subjects (have {self.n} events)")
        prev = context.get("prev") or self.prev
        x = self.vec.transform([self._feats(prev, context, context.get("timestamp"))])
        try:
            probs = self.model.predict_proba(x)[0]
        except Exception as e:  # noqa: BLE001
            return self.empty(key, f"sklearn error: {e}")
        ranked = sorted(zip(self.model.classes_, probs), key=lambda kv: kv[1], reverse=True)[:5]
        cands = [Candidate(str(v), round(float(p), 3), f"logistic P given prev={prev}") for v, p in ranked]
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"trained_on": self.n, "features": len(self.vec.vocabulary_)},
                          guidance=f"Given {prev} in this context: {cands[0].value}")
