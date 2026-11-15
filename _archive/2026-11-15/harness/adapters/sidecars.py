"""Sidecar adapter — classification decisions as events (TAG_TAXONOMY_v0.4, Part B).

Every mim.v1 card is a ruling someone already made about a paper. One facet at a
time becomes the event `subject`, so the engines learn to predict that facet and
the ledger scores them when the next paper is classified.

  facet      event.subject             e.g.
  standing   the card's standing       draft / proposed / declaration
  domain     the card's domain:        Theophysics
  ct         its ct- tag               ct-argument
  ep         its ep- tags (one each)   ep-prediction
  subject    its subject-prefix tags   tp-trinity, math-lean

context = {paper, source_file, folder_class, words}  (`words` = subject-name tokens)
Cards with no value for the facet are skipped, never guessed.

    python -m harness.adapters.sidecars "<folder>\\sidecars"             (standing)
    python -m harness.adapters.sidecars "<folder>\\sidecars" ct
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

from harness.contract import Event

FACETS = ("standing", "domain", "ct", "ep", "subject")
SUBJECT_PREFIXES = ("tp-", "theo-", "phil-", "math-", "phys-", "info-", "cog-",
                    "soc-", "meth-", "cs-", "series-")


def parse_card(path: Path) -> tuple[dict[str, str], list[str]]:
    """Frontmatter fields and tags of one mim.v1 card. ({}, []) if it isn't one."""
    lines = path.read_text(encoding="utf-8", errors="replace").replace("\r", "").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, []
    fields: dict[str, str] = {}
    tags: list[str] = []
    in_tags = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if in_tags and line.strip().startswith("- "):
            tags.append(line.strip()[2:].strip())
            continue
        in_tags = False
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.split(" #")[0].strip().strip('"')
            if k == "tags":
                in_tags = True
            else:
                fields[k] = v
    if fields.get("sidecar") != "mim.v1" or fields.get("type") == "subject-index":
        return {}, []
    return fields, tags


def values_for(facet: str, fields: dict[str, str], tags: list[str]) -> list[str]:
    if facet in ("standing", "domain"):
        return [fields[facet]] if fields.get(facet) else []
    if facet in ("ct", "ep"):
        return [t for t in tags if t.startswith(f"{facet}-")]
    if facet == "subject":
        return [t for t in tags if t.startswith(SUBJECT_PREFIXES)]
    raise ValueError(f"facet must be one of {FACETS}")


def read(folder: str | Path, facet: str = "standing") -> list[Event]:
    folder = Path(folder)
    out = []
    for p in sorted(folder.glob("*.md"), key=lambda q: q.stat().st_mtime):
        fields, tags = parse_card(p)
        if not fields:
            continue
        ts = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
        ctx = {"paper": fields.get("subject", p.stem),
               "source_file": fields.get("source_file", ""),
               "folder_class": fields.get("folder_class", ""),
               "words": fields.get("subject", p.stem).lower()}
        for v in values_for(facet, fields, tags):
            out.append(Event(subject=v, action=f"classify:{facet}", context=ctx,
                             source=f"sidecar:{folder.parent.name}", timestamp=ts,
                             # stable id: re-running the adapter never double-counts a card
                             id="sc-" + hashlib.sha1(f"{p.resolve()}|{facet}|{v}".encode()).hexdigest()[:12]))
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.runner import Runner
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m harness.adapters.sidecars <sidecars folder> [standing|domain|ct|ep|subject]")
    facet = sys.argv[2] if len(sys.argv) > 2 else "standing"
    evs = read(sys.argv[1], facet)
    print(f"read {len(evs)} '{facet}' events; ingested {Runner().ingest(evs)} new")
