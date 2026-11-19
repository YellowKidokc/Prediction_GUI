"""The universal stop record and the adapters that produce it.

Every break, in any language, becomes one StopRecord: a stable `code`, where it
happened, why, the context the models need, and how to resume (rerun command).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class StopRecord:
    code: str                 # stable error family, e.g. py.NameError, html.broken_link
    where: str                # file:line or file#location
    why: str                  # the one-line message
    context: str              # traceback / stderr / snippet for the models
    resume: list[str]         # command that reproduces/continues the run
    files: list[str] = field(default_factory=list)   # project files involved
    adapter: str = "subprocess"

    @property
    def signature(self) -> str:
        """Code plus the message with numbers/paths/quoted names blurred, so the
        same kind of break matches across files."""
        blurred = re.sub(r"'[^']*'|\"[^\"]*\"|\d+|[A-Za-z]:\\\S+|/\S+", "_", self.why)
        return hashlib.sha1(f"{self.code}|{blurred}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signature"] = self.signature
        return d


TB_FILE = re.compile(r'File "([^"]+)", line (\d+)')
TB_LAST = re.compile(r"^(\w+(?:\.\w+)*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(.*))?$", re.M)


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"


def from_python_output(output: str, cmd: list[str], root: Path) -> StopRecord:
    """Adapter: Python traceback -> StopRecord."""
    root = root.resolve()
    frames = [(Path(f), int(n)) for f, n in TB_FILE.findall(output)]
    local = [(f, n) for f, n in frames
             if f.is_absolute() and root in f.resolve().parents or not f.is_absolute()]
    exc = TB_LAST.findall(output)
    name, msg = (exc[-1] if exc else ("NonZeroExit", output.strip().splitlines()[-1:] or [""]))
    if isinstance(msg, list):
        msg = msg[0] if msg else ""
    where = f"{local[-1][0]}:{local[-1][1]}" if local else "?"
    files = []
    for f, _ in local:
        p = f if f.is_absolute() else root / f
        rel = str(p.resolve().relative_to(root))
        if rel not in files:
            files.append(rel)
    return StopRecord(code=f"py.{name.split('.')[-1]}", where=where, why=f"{name}: {msg}".strip(),
                      context=output[-6000:], resume=cmd, files=files, adapter="python")


def from_html_error(err: dict, resume: list[str]) -> StopRecord:
    """Adapter: theophysics-site-repair error_record() -> StopRecord."""
    return StopRecord(code=f"html.{err['error_type']}",
                      where=f"{err['file']}#{err.get('location', '')}",
                      why=err.get("description", err["error_type"]),
                      context=str(err), resume=resume, files=[err["file"]], adapter="html")


def detect(cmd: list[str], root: Path) -> tuple[bool, StopRecord | None, str]:
    """Run the command. Returns (ok, stop_record_or_None, output)."""
    code, out = run(cmd, root)
    if code == 0:
        return True, None, out
    if "Traceback (most recent call last)" in out:
        return False, from_python_output(out, cmd, root), out
    tail = out.strip().splitlines()[-1:] or [f"exit {code}"]
    return False, StopRecord(code=f"proc.exit{code}", where="?", why=tail[0][:300],
                             context=out[-6000:], resume=cmd), out
