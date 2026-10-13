"""Smoke test: python tests/smoke.py -- no GUI, proves the loop end to end."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.contract import Event
from harness.runner import Runner
from harness.registry import sync

db = Path(tempfile.mkdtemp()) / "smoke.db"
r = Runner(db_path=db, context_keys=("subject",))
print("engines loaded:", sorted(r.engines), "| errors:", r.errors)
assert {"frequency_baseline", "recency_baseline"} <= set(r.engines), "baselines did not load"
print("sync:", [(x["name"], x.get("loaded")) for x in sync(r.ledger)])

events = [Event(subject="chanA", action="watch") for _ in range(5)] + \
         [Event(subject="chanB", action="watch") for _ in range(2)]
print("ingested:", r.ingest(events))

preds = r.shadow({"subject": ""})
for p in preds:
    print(f"  {p.engine:20s} top={p.top.value if p.top else None} conf={p.top.confidence if p.top else None}")
tops = {p.engine: (p.top.value if p.top else None) for p in preds}
assert len(preds) >= 5, "expected all five engines to predict"
assert tops["frequency_baseline"] == "chanA" and tops["recency_baseline"] == "chanA", "baselines should say chanA"
assert tops["ensemble_weighted"] is not None, "ensemble should merge peers"
# cpt/river may say chanB (what follows) — that disagreement is the point; the scoreboard settles it

print("resolved:", r.resolve({"subject": ""}, "chanA"))
for row in r.scoreboard():
    print("  ", row)
assert all(row["scored"] == 1 for row in r.scoreboard()), "every engine should have one scored prediction"
print("SMOKE OK")
