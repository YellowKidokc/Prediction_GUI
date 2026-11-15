"""Runner — the loop.

ingest(events)  -> ledger
shadow(context) -> every loaded engine predicts, every prediction is logged
resolve(...)    -> when the outcome arrives, every open prediction for that
                   situation is scored. The scoreboard decides who earns 'live'.
"""
from __future__ import annotations

from typing import Any

from .contract import Event, Prediction, context_key_of
from .ledger import Ledger
from .registry import discover, load, ROOT

DB_PATH = ROOT / "data" / "harness.db"


class Runner:
    def __init__(self, db_path=DB_PATH, context_keys: tuple[str, ...] = ("channel",)) -> None:
        self.ledger = Ledger(db_path)
        self.context_keys = context_keys
        self.engines = {}
        self.errors = {}
        self.reload_engines()

    def reload_engines(self) -> None:
        self.engines, self.errors = {}, {}
        for meta in discover():
            if "error" in meta:
                self.errors[meta["name"]] = meta["error"]; continue
            try:
                eng = load(meta)
                self.engines[meta["name"]] = eng
                target = eng.target
            except Exception as e:  # noqa: BLE001
                self.errors[meta["name"]] = str(e)
                target = meta.get("target", "?")
            # the scoreboard reads the ledger's engine table — keep it in step with the folder
            self.ledger.register_engine(meta["name"], meta["folder"], meta.get("kind", "library"), target, meta)
        self.refit()

    def refit(self) -> None:
        history = self.ledger.events()
        for name, eng in list(self.engines.items()):
            try:
                eng.fit(history)
            except Exception as e:  # noqa: BLE001
                self.errors[name] = f"fit failed: {e}"
                self.engines.pop(name, None)

    def ingest(self, events: list[Event], refit: bool = True) -> int:
        added = sum(1 for e in events if self.ledger.add_event(e))
        if added and refit:
            self.refit()
        return added

    def shadow(self, context: dict[str, Any]) -> list[Prediction]:
        """Ask every engine. Log every answer. Nothing acts.
        Engines with `wants_peers = True` run last and receive the others' predictions
        plus the current hit-rates in context (the ensemble is one of these)."""
        key = context_key_of(context, self.context_keys)
        out = []
        first = [(n, e) for n, e in self.engines.items() if not getattr(e, "wants_peers", False)]
        last = [(n, e) for n, e in self.engines.items() if getattr(e, "wants_peers", False)]
        rates = {row["engine"]: row["hit_rate"] for row in self.ledger.scoreboard()}
        for name, eng in first + last:
            ctx = context
            if getattr(eng, "wants_peers", False):
                ctx = {**context, "_peer_predictions": list(out), "_peer_hit_rates": rates}
            try:
                p = eng.predict(ctx)
            except Exception as e:  # noqa: BLE001
                p = eng.empty(key, why=f"engine error: {e}")
            p.context_key = key
            self.ledger.add_prediction(p)
            out.append(p)
        return out

    def resolve(self, context: dict[str, Any], outcome: str, target: str | None = None) -> int:
        """The outcome for a situation arrived. Score everyone who predicted it."""
        key = context_key_of(context, self.context_keys)
        targets = {target} if target else {e.target for e in self.engines.values()}
        return sum(self.ledger.resolve(key, t, outcome) for t in targets)

    def resolve_event(self, context: dict[str, Any], event: Event) -> int:
        """Score open predictions from a real event, per target: next_subject is
        scored against event.subject, next_<field> against event.context[<field>]."""
        key = context_key_of(context, self.context_keys)
        n = 0
        for t in {e.target for e in self.engines.values()}:
            field = t[5:] if t.startswith("next_") else t
            outcome = event.subject if field == "subject" else str(event.context.get(field, "") or "")
            if outcome:
                n += self.ledger.resolve(key, t, outcome)
        return n

    def scoreboard(self) -> list[dict[str, Any]]:
        return self.ledger.scoreboard()
