"""TEMPLATE — copy this folder to engines/<your_name>/, rename the class, fill in
fit() and predict(). Then run INTAKE.bat on the folder (or just RUN_GUI — the
registry picks it up).

Rules of the house:
  * fit() rebuilds everything from the full history. No incremental state.
  * predict() never raises. Return self.empty(...) when you have nothing.
  * Every Candidate carries a reason a human can read.
  * You do not score yourself. The ledger does.
"""
from __future__ import annotations

from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of


class TemplateEngine(Engine):
    """One paragraph: what signals this engine uses and why they should work."""

    name = "template"            # overwritten by engine.json "name"
    target = "next_subject"      # what you predict — keep it a short noun

    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    def fit(self, events: list[Event]) -> None:
        # Walk the history; build whatever counts/tables you need.
        self.state = {"n": len(events)}

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("channel",))
        if not self.state.get("n"):
            return self.empty(key, "no history")
        return Prediction(
            engine=self.name, target=self.target, context_key=key,
            candidates=[Candidate("REPLACE_ME", 0.0, "explain why this candidate")],
            markers={}, guidance="one line a human could act on")
