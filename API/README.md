# Prediction GUI API v1

This is the public boundary for Coco, FIS, clipboard tools, Lean, canonization, and other programs.
They submit proposals here instead of importing the internal Python package.

## Run

```powershell
python API\server.py
```

The server binds only to `127.0.0.1:2831` by default. Override with `PREDICTION_API_PORT`.

## Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | readiness |
| GET | `/v1/batches` | notification batches |
| GET | `/v1/batches/<id>/items` | spreadsheet rows |
| POST | `/v1/notifications` | submit any standard proposal batch |
| POST | `/v1/atoms/review` | submit an `atom-universal/1.0` object for Lean/canon review |
| POST | `/v1/series/classify` | match names against the authoritative Excel registry |
| POST | `/v1/decisions` | bulk approve, hold, reject, or answer |
| POST | `/v1/reconcile` | mark ruled items reconciled after execution/closure is verified |
| POST | `/v1/batches/<id>/advise` | request bounded Forge advice |

All proposal types use the same row contract. Naming uses the small notification envelope. Lean 4
and canonization use the Universal Atom API Contract from `Faith-through-physics-atoms`; this repo
adapts that contract rather than defining a competing content schema.

Authority is explicit: confidence changes color and review priority, not truth. Read-only/additive work
may auto-approve only when the sender explicitly opts in. File mutations and canon rulings never do.

Series matching checks code, full series name, and older aliases in the newest `LIBR - Series
Multimedia Master` workbook. An unmatched name receives a proposed unique 3-4 character code in the
approval grid; it is not written into the workbook automatically.

Sidecar review uses `PD` (proposed), `RD` (ruled), and `RC` (reconciled). These lifecycle codes do
not replace the separate `standing`, `canon_status`, domain/type, or file-status classifications.
