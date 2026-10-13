# Prediction_GUI

A shadow harness for prediction engines. Every engine predicts, every prediction is
logged, and the ledger scores them against what actually happened. Engines never
score themselves. The scoreboard decides which engine earns `live`.

## First run (Windows)

```
SETUP.bat        creates .venv, installs the engine libraries, runs the smoke test
RUN_GUI.bat      the one window
```

The harness, GUI and baselines are standard-library only. If an engine's library is
missing, that engine abstains ("not available"); nothing crashes.

## Getting events in

| Source | How |
|---|---|
| Any CSV with `subject,action` columns | GUI → Ingest CSV, or `python -m harness.adapters.csv_events file.csv` |
| YouTube watches from Chrome | `HARVEST_CHROME_YOUTUBE.bat` (copies History first; Chrome locks it) |
| Clipboard history from Ditto | `HARVEST_CLIPBOARD_DITTO.bat` (default `%APPDATA%\Ditto\Ditto.db`, or pass a path) |
| Live clipboard, no Ditto | `WATCH_CLIPBOARD.bat` (polls via tkinter; Ctrl+C stops) |

Clipboard events: subject = content kind (`url, path, email, phone, number, json, code, text, longtext`),
context = hash, 80-char preview, length, hour, weekday. Add `--ollama <model>` to either
clipboard mode to tag a one-word `topic` from your local Ollama.

## Engines

| Engine | Library | Predicts | Role |
|---|---|---|---|
| `frequency_baseline` | — | next_subject | floor: most common |
| `recency_baseline` | — | next_subject | floor: half-life weighted |
| `channel_streak` | — | next_channel | 3 in a row on a channel → that channel (silent until context has `channel`) |
| `cpt_sequence` | `cpt` | next_subject | Compact Prediction Tree over sessions |
| `river_online` | `river` | next_subject | online Naive Bayes |
| `sklearn_context` | `scikit-learn` | next_subject | logistic regression, the boring control |
| `bandit_mabwiser` | `mabwiser` | next_subject | LinUCB contextual bandit |
| `ensemble_weighted` | — | next_subject | hit-rate-weighted vote over the others |

New engine: copy `engines/_TEMPLATE`, fill `fit()` and `predict()`, run `INTAKE.bat` on the folder.
`engine.json` may carry `"params": {...}`; they're passed to the engine's constructor.

## Scoring rules

- An engine that returns no candidates **abstains**. The prediction is closed on resolve but never
  counted as a hit or a miss.
- Resolve is per target. In the GUI, pick which target the outcome answers. From code,
  `Runner.resolve_event(context, event)` scores `next_subject` against `event.subject` and
  `next_<field>` against `event.context[<field>]`.

## Check it

```
python tests\smoke.py
```
