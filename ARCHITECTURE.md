# Prediction_GUI boundary

David-OSv3's installed `prediction` package owns the runner, engine discovery,
models, event/prediction contracts, ledger implementation, series matching and
advisory inference. `harness/` contains import adapters only. Its Runner adapter
preserves this application's existing `data/harness.db` path. Old implementations
are retained in `_archive/2026-11-15/<original-path>` with reason notes.

Prediction_GUI displays suggestions and records explicit choices. The localhost
review API opens the ledger without loading or fitting inference engines. It
never auto-approves an incoming suggestion based on confidence. It imports App
160 from the same installed `shared.meq_namer` module as FIS.

`notifications/adapters/fis_plan.py` imports immutable David-OS plans into the
existing notification inbox. A decision binds to the exact plan hash, row IDs,
actor and note through `shared.review`. Held rows and edited names cannot be
approved against an old plan; edits must return to David-OS for a new proposal.
The GUI records the choice before returning its receipt. David-OS validates the
receipt and uses its existing guarded executor; the GUI never changes files.

Install `requirements-david-os.txt` plus the existing `requirements.txt` before
launching. For paired development, an editable David-OS install works too.
Start `python API/server.py` (localhost port 2831 by default); configure FIS with
`PREDICTION_GUI_URL` if using another address. Set `PREDICTION_LEDGER` to select
an explicit review database. Existing GUI databases were not migrated or moved.

The companion PR must be reviewed with David-OSv3 PR #3. No source corpus or
live registry assignment migration was performed during this cleanup.
