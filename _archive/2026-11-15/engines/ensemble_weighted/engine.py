"""Ensemble — the combiner. Not a download; this is the meta-predictor from the spec.

Reads the scoreboard, weights every *other* engine's candidates by that engine's
recent hit-rate (plus a small prior so new engines get a vote), sums the votes,
and returns the merged ranking. When the ensemble beats every member on the
scoreboard, two members are seeing different parts of the signal — and the
markers tell you which two carried the vote.

It never predicts on its own; it needs the runner to hand it the others'
predictions via context["_peer_predictions"] (the runner does this automatically
when an engine declares `wants_peers = True`).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of


class EnsembleWeighted(Engine):
    """Hit-rate-weighted vote over every other engine's top-5 candidates."""

    name = "ensemble_weighted"
    target = "next_subject"
    wants_peers = True
    prior = 0.25          # weight for an engine with no scored history yet
    floor = 0.05          # never silence an engine completely

    def fit(self, events: list[Event]) -> None:
        return  # nothing to learn; the ledger carries the weights

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("subject",))
        peers: list[Prediction] = context.get("_peer_predictions") or []
        rates: dict[str, float | None] = context.get("_peer_hit_rates") or {}
        if not peers:
            return self.empty(key, "no peer predictions supplied")
        votes: dict[str, float] = defaultdict(float)
        who: dict[str, list[str]] = defaultdict(list)
        for p in peers:
            if p.engine == self.name or p.target != self.target:
                continue
            r = rates.get(p.engine)
            w = max(self.floor, self.prior if r is None else r)
            for rank, c in enumerate(p.candidates[:5]):
                votes[c.value] += w * c.confidence / (rank + 1)
                who[c.value].append(p.engine)
        if not votes:
            return self.empty(key, "peers had no candidates")
        total = sum(votes.values()) or 1.0
        ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)[:5]
        cands = [Candidate(v, round(s / total, 3), f"voted by {', '.join(sorted(set(who[v])))}") for v, s in ranked]
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"weights": {k: (self.prior if v is None else v) for k, v in rates.items()}},
                          guidance=f"Weighted vote: {cands[0].value} ({cands[0].reason})")
