"""The escalation ladder.

    run command -> it stops -> StopRecord
    tier 0  casebook: same signature solved before -> replay the fix
    tier 1  Jev writes a fix, a separate Jev call votes YES/NO   (3 tries)
    tier 2  DeepSeek writes, Jev votes                           (2 tries)
    tier 3  top writer (Opus) writes, top approver (Fable) votes (2 tries, if configured)
    tier 4  human queue

A fix only counts when the approver says YES *and* the command (plus the
optional --check command) passes in a sandbox copy. Only then is it applied to
the real folder (with backups) and written to the casebook. Every writer sees
the casebook learnings and the earlier failed attempts.
"""
from __future__ import annotations

import difflib
import json
import shutil
import tempfile
import time
from pathlib import Path

from . import casebook, fixers, notify
from .llm import extract_json, redact, tiers, yes_no
from .stop import StopRecord, detect, run

IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "node_modules", "__pycache__",
                                "backups", ".BACKSIDE", "*.pyc")
MAX_FILE_CHARS = 40_000

WRITER_SYS = """You fix a program that stopped. You get a stop record (code, where, why, the
traceback/output), the full text of the project files involved, learnings from earlier
solved cases (use them even if they do not obviously match), and any earlier failed
attempts with the output they produced.
Make the smallest change that lets the command run correctly. Do not delete features,
do not silence errors with bare try/except, do not change the meaning of content.
Reply with ONLY a JSON object:
{"fix_summary": "one sentence: what was wrong and what you changed",
 "edits": [{"file": "path relative to project root", "content": "the COMPLETE new file text"}]}"""

APPROVER_SYS = """You are the approver. Another model proposed a fix for a program that stopped.
You see the stop record and the diff. Approve only if the change plausibly fixes the
cause, is minimal, and does not hide the error or remove behavior.
First word of your reply must be YES or NO, then one sentence why."""


def _safe_rel(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise ValueError(f"edit escapes project root: {rel}")
    return p


def _files_blob(root: Path, files: list[str]) -> str:
    parts = []
    for rel in files[:6]:
        p = root / rel
        if p.is_file():
            parts.append(f"=== {rel} ===\n{p.read_text(encoding='utf-8', errors='replace')[:MAX_FILE_CHARS]}")
    return "\n\n".join(parts) or "(no project files identified; infer from the output)"


def _diff(root: Path, edits: list[dict]) -> str:
    out = []
    for e in edits:
        p = root / e["file"]
        old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        out.extend(difflib.unified_diff(old.splitlines(), e["content"].splitlines(),
                                        f"a/{e['file']}", f"b/{e['file']}", lineterm=""))
    return "\n".join(out)[:20_000]


def _apply(root: Path, edits: list[dict], backup_dir: Path | None = None) -> None:
    for e in edits:
        p = _safe_rel(root, e["file"])
        if backup_dir and p.exists():
            b = backup_dir / e["file"]
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, b)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(e["content"], encoding="utf-8")


def sandbox_check(root: Path, edits: list[dict], cmd: list[str],
                  check: list[str] | None) -> tuple[bool, str]:
    """Copy the project, apply edits, rerun command (+ check). The 'did it fix it
    or break it' test."""
    with tempfile.TemporaryDirectory(prefix="unsticker_") as tmp:
        box = Path(tmp) / "box"
        shutil.copytree(root, box, ignore=IGNORE)
        _apply(box, edits)
        code, out = run(cmd, box)
        if code != 0:
            return False, f"command still fails (exit {code}):\n{out[-3000:]}"
        if check:
            code, cout = run(check, box)
            if code != 0:
                return False, f"command passed but check failed (exit {code}):\n{cout[-3000:]}"
            out += "\n--- check ---\n" + cout
        return True, out[-2000:]


def _attempt(root: Path, stop: StopRecord, writer, approver, prior: list[dict],
             cmd: list[str], check: list[str] | None, temp: float) -> dict:
    user = json.dumps({
        "stop": stop.to_dict(),
        "learnings": casebook.learnings(stop.code),
        "failed_attempts": [{"by": a["by"], "summary": a.get("summary"), "result": a.get("result")}
                            for a in prior[-4:]],
    }, indent=1) + "\n\nPROJECT FILES:\n" + _files_blob(root, stop.files)
    row = {"by": writer.name, "approver": approver.name}
    try:
        prop = extract_json(writer.chat(WRITER_SYS, user, temperature=temp, max_tokens=8000))
        edits = [{"file": e["file"], "content": e["content"]} for e in prop.get("edits", [])]
        for e in edits:
            _safe_rel(root, e["file"])
        if not edits:
            raise ValueError("writer returned no edits")
    except Exception as exc:  # bad JSON, path escape, call failure
        row.update(result=f"writer failed: {redact(exc)}")
        return row
    row.update(summary=prop.get("fix_summary", ""), edits=edits)
    diff = _diff(root, edits)
    try:
        verdict_text = approver.chat(APPROVER_SYS, f"STOP:\n{json.dumps(stop.to_dict())}\n\nDIFF:\n{diff}",
                                     temperature=0.0, max_tokens=1500)
    except Exception as exc:
        row.update(vote="UNKNOWN", result=f"approver failed: {redact(exc)}")
        return row
    vote = yes_no(verdict_text)
    row.update(vote=vote, vote_reason=verdict_text.strip()[:300])
    if vote != "YES":
        row["result"] = f"approver voted {vote}: {verdict_text.strip()[:200]}"
        return row
    ok, out = sandbox_check(root, edits, cmd, check)
    if not ok and _progressed(stop, out, root):
        row.update(passed=True, result="PROGRESS: this error is gone, a different one is next")
    else:
        row.update(passed=ok, result=("PASS" if ok else out))
    return row


def unstick(root: Path, cmd: list[str], check: list[str] | None = None,
            max_stops: int = 5, log=print) -> bool:
    root = root.resolve()
    T = tiers()
    ladder = [("jev", T["jev"], T["jev"], 3),
              ("deepseek", T["deepseek"], T["jev"], 2)]
    if T["top_writer"].ready and T["top_approver"].ready:
        ladder.append(("top", T["top_writer"], T["top_approver"], 2))
    log(f"[unsticker] tiers: " + ", ".join(f"{n}={w.name}->{a.name}" for n, w, a, _ in ladder))

    for _ in range(max_stops):
        ok, stop, out = detect(cmd, root)
        if ok:
            log("[unsticker] command runs clean.")
            casebook.ledger("clean", cmd=cmd, root=str(root))
            return True
        log(f"[unsticker] STOP {stop.code} at {stop.where}: {stop.why}")
        casebook.ledger("stop", stop=stop.to_dict())
        fixed = False

        # tier 0a: fixers WE wrote for this error code (no model call)
        for fn in fixers.for_code(stop.code):
            try:
                fx = fn(stop, root)
            except Exception as exc:
                log(f"[tier0] fixer {fn.__name__} crashed: {exc}")
                continue
            if not fx or not fx.edits:
                continue
            ok, out = sandbox_check(root, fx.edits, cmd, check)
            log(f"[tier0] fixer {fn.__name__}: {fx.summary} -> {'PASS' if ok else 'still fails'}")
            if ok or _progressed(stop, out, root):
                _apply(root, fx.edits, _backup_dir(root))
                casebook.ledger("fixed", tier=0, fixer=fn.__name__, stop=stop.to_dict())
                fixed = True
                break

        # tier 0b: replay a fix the casebook already proved for this exact signature
        for case in ([] if fixed else casebook.exact(stop.signature)):
            if case.get("edits") and all((root / e["file"]).exists() for e in case["edits"]):
                ok, out = sandbox_check(root, case["edits"], cmd, check)
                if ok or _progressed(stop, out, root):
                    _apply(root, case["edits"], _backup_dir(root))
                    log(f"[tier0] replayed casebook fix: {case['fix_summary']}")
                    casebook.ledger("fixed", tier=0, stop=stop.to_dict())
                    fixed = True
                    break
        attempts: list[dict] = []
        for tier_name, writer, approver, tries in ([] if fixed else ladder):
            for i in range(tries):
                row = _attempt(root, stop, writer, approver, attempts, cmd, check, temp=0.2 + 0.25 * i)
                row["tier"] = tier_name
                attempts.append(row)
                log(f"[{tier_name} #{i+1}] {writer.name} wrote: {row.get('summary','-')[:120]}")
                log(f"           vote={row.get('vote','-')} result={str(row.get('result'))[:160]}")
                casebook.ledger("attempt", stop=stop.signature,
                                **{k: v for k, v in row.items() if k != "edits"})
                if row.get("passed"):
                    _apply(root, row["edits"], _backup_dir(root))
                    casebook.record(stop.to_dict(), row["summary"], row["edits"],
                                    solved_by=writer.name, approved_by=approver.name)
                    draft = _write_draft_fixer(root, stop, row)
                    log(f"[unsticker] FIXED by {writer.name}, approved by {approver.name}; "
                        f"casebook updated, draft fixer {draft}")
                    notify.fixed_by_model(stop.to_dict(), row["summary"], writer.name,
                                          approver.name, draft)
                    fixed = True
                    break
            if fixed:
                break
        if not fixed:
            casebook.to_human(stop.to_dict(), [{k: v for k, v in a.items() if k != "edits"} for a in attempts])
            notify.needs_human(stop.to_dict(), len(attempts))
            log("[tier4] nobody solved it -> data/human_queue.jsonl + inbox")
            return False
        # loop: rerun; a fix can expose the next stop
    log("[unsticker] hit max_stops; handing to human.")
    return False


def _progressed(stop: StopRecord, out: str, root: Path) -> bool:
    """A fixer that clears THIS error but uncovers a different one still counts:
    the loop reruns and handles the next stop."""
    if "Traceback" not in out:
        return False
    from .stop import from_python_output
    nxt = from_python_output(out, stop.resume, root)
    return nxt.signature != stop.signature


DRAFTS = Path(__file__).resolve().parent / "fixers" / "drafts"


def _write_draft_fixer(root: Path, stop: StopRecord, row: dict) -> str:
    """A model solved a code we had no fixer for. Leave a draft for us to turn
    into a general fixer; until then the casebook replays the exact fix."""
    DRAFTS.mkdir(parents=True, exist_ok=True)
    name = f"{stop.code.replace('.', '_')}_{stop.signature}.py"
    body = f'''"""DRAFT fixer, written by {row["by"]}, approved by {row["approver"]}.
Code: {stop.code}
Why:  {stop.why}
Fix:  {row.get("summary", "")}

TODO (human): generalize this into a real fixer, move it up into unsticker/fixers/,
and delete this draft. The model's exact edit is in data/casebook.jsonl.
"""
from unsticker.fixers import Fix, fixer


# @fixer("{stop.code}")   # uncomment once generalized
def draft_{stop.signature}(stop, root):
    return None
'''
    (DRAFTS / name).write_text(body, encoding="utf-8")
    return f"fixers/drafts/{name}"


def _backup_dir(root: Path) -> Path:
    d = root / "backups" / ("unsticker_" + time.strftime("%Y%m%d_%H%M%S"))
    d.mkdir(parents=True, exist_ok=True)
    return d
