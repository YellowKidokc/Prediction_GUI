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
assert {row["engine"] for row in r.scoreboard()} >= set(r.engines), "Runner must register engines itself (GUI never calls sync)"
print("sync:", [(x["name"], x.get("loaded")) for x in sync(r.ledger)])

events = [Event(subject="chanA", action="watch") for _ in range(5)] + \
         [Event(subject="chanB", action="watch") for _ in range(2)]
print("ingested:", r.ingest(events))

preds = r.shadow({"subject": ""})
for p in preds:
    print(f"  {p.engine:20s} top={p.top.value if p.top else None} conf={p.top.confidence if p.top else None}")
tops = {p.engine: (p.top.value if p.top else None) for p in preds}
assert len(preds) >= 8, "expected all eight engines to predict"
import importlib.util as _iu
have = {n: _iu.find_spec(m) is not None for n, m in [("sklearn_context", "sklearn"), ("bandit_mabwiser", "mabwiser")]}
print("libraries present:", have)
for n in [n for n, ok in have.items() if ok]:
    assert tops[n] in ("chanA", "chanB"), f"{n} should rank a real subject"
assert tops["channel_streak"] is None, "no channel in context -> streak engine abstains"
assert tops["frequency_baseline"] == "chanA" and tops["recency_baseline"] == "chanA", "baselines should say chanA"
assert tops["ensemble_weighted"] is not None, "ensemble should merge peers"
# cpt/river may say chanB (what follows) — that disagreement is the point; the scoreboard settles it

print("resolved:", r.resolve({"subject": ""}, "chanA"))
for row in r.scoreboard():
    print("  ", row)
board = {row["engine"]: row for row in r.scoreboard()}
assert board["channel_streak"]["scored"] == 0 and board["channel_streak"]["pending"] == 0, "abstention closed, not scored"
assert all(row["scored"] == (1 if tops[n] else 0) for n, row in board.items()), "speakers scored once, abstainers never"

# per-target resolve: three on chanX -> streak predicts next_channel=chanX, resolve_event scores it
r.ingest([Event(subject=f"vid{i}", action="watch", context={"channel": "chanX"}, timestamp=f"2099-01-0{i+1}T10:00:00+00:00") for i in range(3)])
preds = {p.engine: p for p in r.shadow({"subject": "x"})}
assert preds["channel_streak"].top.value == "chanX", preds["channel_streak"].guidance
print("resolve_event:", r.resolve_event({"subject": "x"}, Event(subject="vid9", action="watch", context={"channel": "chanX"})))
assert {row["engine"]: row for row in r.scoreboard()}["channel_streak"]["hits"] == 1

# clipboard: classifier + Ditto reader against a mock Ditto.db
import sqlite3
from harness.adapters import clipboard as cb
assert [cb.kind_of(t) for t in ("https://x.com/a", "C:\\Users\\d", "a@b.co", "42.5", "def f():\n    return 1", "hello")] == \
    ["url", "path", "email", "number", "code", "text"]
ditto = db.parent / "Ditto.db"; c = sqlite3.connect(ditto)
c.execute("CREATE TABLE Main (lID INTEGER PRIMARY KEY, lDate INTEGER, mText TEXT, bIsGroup INTEGER, lastPasteDate INTEGER)")
c.executemany("INSERT INTO Main(lDate,mText,bIsGroup,lastPasteDate) VALUES (?,?,?,?)",
              [(1760000000, "https://a.com", 0, 1760000100), (1760000200, "grp", 1, 0), (1760000300, "", 0, 0)])
c.commit(); c.close()
evs = cb.read_ditto(ditto)
assert [(e.subject, e.action) for e in evs] == [("url", "copy"), ("url", "paste")], evs
print("ditto:", r.ingest(evs), "clipboard events ingested")
print("SMOKE OK")
