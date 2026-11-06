"""Read a folder into documents. Standard library only; pdf needs pypdf (else skipped)."""
from __future__ import annotations

import html
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".py", ".log", ".rst", ".tex"}
SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__", ".venv", ".trash"}
MAX_CHARS = 200_000


@dataclass
class Doc:
    path: str
    ext: str
    text: str
    meta: dict = field(default_factory=dict)


def _docx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _pdf(p: Path) -> str:
    from pypdf import PdfReader  # optional
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def read_file(p: Path) -> str | None:
    ext = p.suffix.lower()
    try:
        if ext == ".docx":
            return _docx(p)
        if ext == ".pdf":
            return _pdf(p)
        if ext in TEXT_EXT:
            raw = p.read_text("utf-8", errors="ignore")
            if ext in (".html", ".htm"):
                raw = html.unescape(re.sub(r"<(script|style).*?</\1>|<[^>]+>", " ", raw, flags=re.S | re.I))
            return raw
    except Exception:  # noqa: BLE001  unreadable file = skipped, not fatal
        return None
    return None


def walk(folder: str | Path, limit: int | None = None) -> list[Doc]:
    root = Path(folder)
    docs: list[Doc] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        text = read_file(p)
        if text is None or not text.strip():
            continue
        docs.append(Doc(str(p.relative_to(root)), p.suffix.lower(), text[:MAX_CHARS]))
        if limit and len(docs) >= limit:
            break
    return docs


def profile(folder: str | Path) -> dict:
    """What the planner sees: counts, types, sizes, a few short samples. Never the whole corpus."""
    root = Path(folder)
    all_ext = Counter(p.suffix.lower() or "(none)" for p in root.rglob("*")
                      if p.is_file() and not any(x in SKIP_DIRS for x in p.relative_to(root).parts))
    docs = walk(root)
    words = [len(d.text.split()) for d in docs]
    md = [d for d in docs if d.ext in (".md", ".markdown")]
    return {
        "folder": str(root), "files_total": sum(all_ext.values()), "readable_docs": len(docs),
        "extensions": dict(all_ext.most_common(15)),
        "words_total": sum(words), "words_median": sorted(words)[len(words) // 2] if words else 0,
        "markdown_with_frontmatter": sum(d.text.startswith("---") for d in md),
        "markdown_with_wikilinks": sum("[[" in d.text for d in md),
        "samples": [{"path": d.path, "start": d.text[:400]} for d in docs[:: max(1, len(docs) // 5)][:5]],
    }
