# Prediction_GUI

## Clone → setup → run

Python 3.11+ and Git are required. The clone can live in any folder, including a
folder with spaces or a network share. The virtual environment lives separately
on local disk: `%LOCALAPPDATA%/david-os/venvs` on Windows, `~/.cache/david-os/venvs`
on Linux, or `~/Library/Caches/david-os/venvs` on macOS. Each clone gets its own
stable environment. Set `DAVID_OS_VENV` to override it with a local disk path;
setup rejects network mounts on Linux and non-fixed drives on Windows.

```sh
git clone --branch cleanup/v3-consolidation https://github.com/YellowKidokc/Prediction_GUI.git
cd Prediction_GUI
python setup_env.py --core
python run.py
```

No activation or sibling checkout is required. Windows users can use `py` in place
of `python`. Re-run setup after moving the clone or updating its dependency pin.
`python run.py` uses the same local environment from any working directory; give
its absolute path when calling from outside the clone.

Copy `config.example.yaml` to `config.yaml` if you need custom paths, and set
`DAVID_OS_CONFIG` to that file's absolute path. Paths inside the YAML resolve
relative to the YAML file. Environment variables override configured paths.
`DAVID_OS_STATE_DIR`, `DAVID_OS_REFERENCE_DB`, `DAVID_OS_LEXICON`,
`THEOPHYSICS_SERIES_FOLDER` and `DAVID_OS_CANON_RULES` override the matching paths.
`THEOPHYSICS_SERIES_REGISTRY` names an explicit series workbook; matching reports
a missing workbook until one is configured. `DAVID_OS_REGISTRY` selects the central
identity SQLite database. No personal corpus or remote disk is required for setup.

API keys and service tokens come from the process environment only. For hosted
DeepSeek use `DEEPSEEK_BACKEND=api` and `DEEPSEEK_API_KEY`; the default local Ollama
backend needs no key. Never put keys in YAML, source files, launchers or a token
JSON file. The optional YAML loader rejects credential fields. `config.yaml` and
`.env` files are ignored by Git; the application does not load `.env` files.

`SETUP.bat` runs the same setup; all Windows launchers use `run.py` and the local
environment. Omit `--core` to install optional prediction/NLP libraries too.
The core GUI needs tkinter (on Debian/Ubuntu: `sudo apt-get install python3-tk`).

The required backend is declared in `requirements-david-os.txt` as a PEP 508
Git dependency pinned to an immutable David-OS commit. Setup always installs
this file. Imports use the installed `prediction` and `shared` packages, with no
sibling-folder lookup or David-OS `PYTHONPATH` requirement. Test with
`python run.py -m unittest discover -s tests -p 'test_*.py'` and
`python run.py tests/smoke.py`.


A shadow harness for prediction engines. Every engine predicts, every prediction is
logged, and the ledger scores them against what actually happened. Engines never
score themselves. The scoreboard decides which engine earns `live`.

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

## Notification and approval grid

The shadow harness now has a first-class review mailbox. Click **Notification inbox** in the GUI.
Every source uses the same spreadsheet-shaped envelope: current value, proposal, confidence,
editable final value, reason, and decision. Rows can be checked individually or all at once and
then approved, held, or rejected as a batch.

Starter templates live in `notifications/templates.json`; add another JSON entry to extend the
catalog without changing Python. The included templates are approval batch, blocked question,
and incident/correction. They are examples, not a fixed limit.

Confidence bands are visible: green >= 90%, amber 60-89%, red < 60%, gray unknown. Amber batches
automatically request concise advice through Forge (`FORGE_URL`, default `http://127.0.0.1:8790`),
but AI advice never decides an item. High confidence only auto-approves when the caller explicitly
marks an item `risk_class=read_only|additive` and `auto_approvable=true`. Mutations and canon
decisions always remain pending.

```
python -m notifications.cli demo
python -m notifications.cli list
python -m notifications.cli import-names naming_plan.csv
```

Naming plans from FIS, Coco, or another program use `current_path, proposed_name, confidence,
reason`. They become editable rows in the same grid. Naming is a mutation class, so even a 100%
confidence proposal is never auto-applied.

## Scoring rules

- An engine that returns no candidates **abstains**. The prediction is closed on resolve but never
  counted as a hit or a miss.
- Resolve is per target. In the GUI, pick which target the outcome answers. From code,
  `Runner.resolve_event(context, event)` scores `next_subject` against `event.subject` and
  `next_<field>` against `event.context[<field>]`.

## Check it

```
python run.py tests/smoke.py
```

## NLP pipelines (DeepSeek plans, you lock)

GUI → **NLP pipelines (DeepSeek)**, or `NLP.bat <command>`.

1. **Plan**: pick a folder and type a goal. The program profiles the folder (file types, sizes,
   frontmatter and wikilink counts, five short samples). DeepSeek gets that profile plus the
   step catalog and picks the steps and their settings. It never sees the whole corpus at this stage.
2. **Run**: results go to `data/nlp/<name>/runs/v<N>_<time>/` as `results.json` and `report.md`.
   "Run sample" runs 20 documents first, so a bad plan costs seconds, not an hour.
3. **Revise**: write what's wrong. DeepSeek gets the old plan, your feedback, and sample output, and
   writes the next version. You can also edit the plan JSON by hand. Every version is kept.
4. **Lock**: freezes that version. Each run also drops a row in the Notification inbox, and
   approving the row locks that version.

Steps: `stats, markdown_structure, keywords, entities, near_duplicates` (standard library),
`clusters` (scikit-learn), and `summarize, classify, extract` (DeepSeek). Step names the planner
invents are dropped. If DeepSeek can't be reached, Plan falls back to a rule-based plan and says so.

| Setting | Default |
|---|---|
| `DEEPSEEK_BACKEND` | `ollama` (local). `api` = api.deepseek.com |
| `DEEPSEEK_MODEL` | `deepseek-r1:8b` (Ollama; if that exact tag is missing, the first installed `deepseek-r1:*` is used) / `deepseek-chat` (API). Faster for per-note summaries: `qwen3:4b-instruct` |
| `DEEPSEEK_API_KEY` | needed only for `api` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` |

```
python -m nlp.cli plan vault "path/to/corpus" "find duplicates and group by law"
python -m nlp.cli run vault --limit 20
python -m nlp.cli revise vault "classify into the 10 laws instead of topics"
python -m nlp.cli lock vault
python tests\test_nlp.py
```

## Consolidated ownership

Install `requirements-david-os.txt` before launching this version. Prediction
implementations now come from David-OSv3; this repository displays results and
records explicit approvals. See [ARCHITECTURE.md](ARCHITECTURE.md) for the FIS
plan/receipt boundary and preserved ledger paths.
