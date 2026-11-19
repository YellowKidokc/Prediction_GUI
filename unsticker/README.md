# Unsticker

When a program stops, climb a ladder. Each fix must get an approver's YES and pass a sandbox rerun before it touches the real folder.

```
python -m unsticker --root <project> [--check "pytest -q"] -- python script.py
```

| Tier | Who | Cost |
|---|---|---|
| 0a | `fixers/` — code WE wrote, keyed by error code | free |
| 0b | casebook replay — a fix already proven for this exact signature | free |
| 1 | Jev writes, Jev approves (3 tries) | cheap OpenRouter |
| 2 | DeepSeek writes, Jev approves (2 tries) | cheap |
| 3 | Opus 5.5 writes, Fable 5.2 approves (2 tries) | expensive |
| 4 | inbox + Windows toast → you | — |

A fix that clears its error but exposes a different one counts as progress, and the loop continues with the next stop.

**The rule:** every time a model (or you) solves a new error code, generalize it into a fixer in `fixers/`. A draft lands in `fixers/drafts/` automatically. After that, the code is tier 0 forever.

Config (env): `OPENROUTER_API_KEY`, `JEV_MODEL` (default `~deepseek/deepseek-flash-latest`), `DEEPSEEK_API_KEY`, `TOP_WRITER_MODEL`, `TOP_APPROVER_MODEL`.

Error codes: `py.<Exception>`, `html.<error_type>` (from theophysics-site-repair), `proc.exit<N>`.

Demo: `demo/pristine` has two planted breaks. Copy it to `demo/broken` and run with `PYTHONIOENCODING=cp1252`.

Data: `data/casebook.jsonl`, `data/ledger.jsonl`, `data/human_queue.jsonl`.
