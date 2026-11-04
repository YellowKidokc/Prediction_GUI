# Sidecar decision lifecycle

| Code | State | Meaning |
|---|---|---|
| `PD` | Proposed | Machine observation or suggestion. No authority and no source mutation. |
| `RD` | Ruled | A human approved, edited, held, or rejected it. The proposal remains in history. |
| `RC` | Reconciled | The ruling was executed and verified, or explicitly closed/superseded. |

Allowed transitions are `PD -> RD -> RC`. These codes do not replace document `standing`, machine
`canon_status`, domain/type codes, or the source file lifecycle.
