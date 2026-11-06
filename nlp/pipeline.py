"""Plan -> run -> look -> revise -> ... -> lock.

Everything lives in data/nlp/<name>/:
  pipeline.json      folder, goal, every plan version, which one is locked
  runs/v<N>_<ts>/    results.json (per document + _corpus), report.md

A locked pipeline is frozen: revise refuses, run uses the locked plan. Unlock is explicit.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import llm, scan, steps

DATA = Path(__file__).resolve().parent.parent / "data" / "nlp"

PLANNER = """You design NLP pipelines over a folder of documents. You are given the folder profile,
the user's goal, and the catalog of steps that exist. Choose the smallest ordered set of steps that
serves the goal. Only use step names from the catalog, prefer available ones, and set params.
Return {"steps": [{"step": name, "params": {...}, "why": short}], "notes": short}."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "pipeline"


def rule_plan(prof: dict, goal: str) -> dict:
    """Used when DeepSeek is unreachable. Honest and boring."""
    plan = [{"step": "stats", "params": {}, "why": "baseline size of every document"},
            {"step": "keywords", "params": {"top": 10}, "why": "what each document is about"}]
    if prof.get("markdown_with_frontmatter") or prof.get("markdown_with_wikilinks"):
        plan.append({"step": "markdown_structure", "params": {}, "why": "vault metadata and links"})
    plan.append({"step": "near_duplicates", "params": {"threshold": 0.8}, "why": "find copies"})
    if steps.available("clusters") and prof.get("readable_docs", 0) >= 6:
        plan.append({"step": "clusters", "params": {"k": min(8, max(2, prof["readable_docs"] // 10))},
                     "why": "topic groups"})
    return {"steps": plan, "notes": "rule-based plan (DeepSeek unavailable)", "planner": "rules"}


def _clean(plan: dict) -> dict:
    ok = [s for s in plan.get("steps", []) if isinstance(s, dict) and s.get("step") in steps.CATALOG]
    for s in ok:
        s.setdefault("params", {})
    plan["steps"] = ok
    return plan


class Pipeline:
    def __init__(self, name: str) -> None:
        self.dir = DATA / slug(name)
        self.file = self.dir / "pipeline.json"
        self.data = json.loads(self.file.read_text("utf-8")) if self.file.exists() else {
            "name": slug(name), "folder": None, "goal": "", "versions": [], "locked": None}

    # ---- persistence --------------------------------------------------
    @classmethod
    def all(cls) -> list["Pipeline"]:
        return [cls(f.parent.name) for f in sorted(DATA.glob("*/pipeline.json"))]

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2), "utf-8")

    @property
    def current(self) -> dict | None:
        if self.data["locked"]:
            return next(v for v in self.data["versions"] if v["v"] == self.data["locked"])
        return self.data["versions"][-1] if self.data["versions"] else None

    def _add_version(self, plan: dict, feedback: str = "") -> dict:
        v = {"v": len(self.data["versions"]) + 1, "created": _now(), "feedback": feedback, "plan": plan}
        self.data["versions"].append(v); self.save()
        return v

    # ---- the loop -----------------------------------------------------
    def plan(self, folder: str, goal: str) -> dict:
        if self.data["locked"]:
            raise RuntimeError(f"locked at v{self.data['locked']}; unlock first")
        self.data["folder"], self.data["goal"] = str(folder), goal
        prof = scan.profile(folder)
        try:
            plan = _clean(llm.chat_json(PLANNER, json.dumps(
                {"goal": goal, "profile": prof, "catalog": steps.describe()})))
            plan["planner"] = f"deepseek/{llm.backend()}"
            if not plan["steps"]:
                raise llm.LLMUnavailable("planner returned no usable steps")
        except llm.LLMUnavailable as e:
            plan = rule_plan(prof, goal); plan["planner_error"] = str(e)
        return self._add_version(plan)

    def revise(self, feedback: str) -> dict:
        if self.data["locked"]:
            raise RuntimeError(f"locked at v{self.data['locked']}; unlock first")
        cur = self.current
        if not cur:
            raise RuntimeError("no plan yet")
        last = self.last_run()
        sample = {}
        if last:
            res = json.loads((last / "results.json").read_text("utf-8"))
            sample = {k: res[k] for k in list(res)[:4]}
        try:
            plan = _clean(llm.chat_json(PLANNER + "\nRevise the previous plan to satisfy the feedback.", json.dumps(
                {"goal": self.data["goal"], "previous_plan": cur["plan"], "feedback": feedback,
                 "output_sample": sample, "catalog": steps.describe()}, default=str)[:60000]))
            plan["planner"] = f"deepseek/{llm.backend()}"
        except llm.LLMUnavailable as e:
            raise RuntimeError(f"DeepSeek unavailable, edit the plan JSON by hand instead: {e}") from e
        return self._add_version(plan, feedback)

    def set_plan(self, plan: dict, note: str = "hand edit") -> dict:
        if self.data["locked"]:
            raise RuntimeError("locked; unlock first")
        return self._add_version(_clean(plan), note)

    def run(self, limit: int | None = None, progress=lambda msg: None) -> Path:
        cur = self.current
        if not cur or not self.data["folder"]:
            raise RuntimeError("plan first")
        docs = scan.walk(self.data["folder"], limit)
        progress(f"read {len(docs)} documents")
        out: dict = {d.path: {} for d in docs}; out["_corpus"] = {}
        timing = []
        for s in cur["plan"]["steps"]:
            name = s["step"]
            if not steps.available(name):
                timing.append({"step": name, "skipped": f"needs {steps.CATALOG[name]['needs']}"}); continue
            progress(f"step {name}…"); t = time.time()
            try:
                steps.CATALOG[name]["fn"](docs, s.get("params", {}), out)
                timing.append({"step": name, "seconds": round(time.time() - t, 2)})
            except Exception as e:  # noqa: BLE001  one bad step must not lose the others
                timing.append({"step": name, "error": f"{type(e).__name__}: {e}"})
        out["_corpus"]["_run"] = {"version": cur["v"], "documents": len(docs), "steps": timing, "at": _now()}
        run_dir = self.dir / "runs" / f"v{cur['v']}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results.json").write_text(json.dumps(out, indent=2, default=str), "utf-8")
        (run_dir / "report.md").write_text(self.report(out), "utf-8")
        progress(f"done → {run_dir}")
        return run_dir

    def last_run(self) -> Path | None:
        runs = sorted((self.dir / "runs").glob("v*_*")) if (self.dir / "runs").exists() else []
        return runs[-1] if runs else None

    def lock(self, version: int | None = None) -> int:
        v = version or (self.data["versions"][-1]["v"] if self.data["versions"] else None)
        if not v:
            raise RuntimeError("nothing to lock")
        self.data["locked"] = v; self.data["locked_at"] = _now(); self.save()
        return v

    def unlock(self) -> None:
        self.data["locked"] = None; self.save()

    # ---- human view ---------------------------------------------------
    def report(self, out: dict) -> str:
        c = out.get("_corpus", {}); r = c.get("_run", {})
        lines = [f"# {self.data['name']} — v{r.get('version')}", "", f"Folder: `{self.data['folder']}`",
                 f"Goal: {self.data['goal']}", f"Documents: {r.get('documents')}", "", "## Steps"]
        lines += [f"- {json.dumps(s)}" for s in r.get("steps", [])]
        if c.get("top_terms"):
            lines += ["", "## Corpus top terms", ", ".join(c["top_terms"][:30])]
        if c.get("clusters"):
            lines += ["", "## Clusters"] + [f"- {k}: {v}" for k, v in c["clusters"].items()]
        if c.get("near_duplicates") is not None:
            lines += ["", f"## Near duplicates ({len(c['near_duplicates'])})"]
            lines += [f"- {p['a']} ≈ {p['b']} ({p['jaccard']})" for p in c["near_duplicates"][:50]]
        lines += ["", "## Documents (first 40)"]
        for path in [k for k in out if k != "_corpus"][:40]:
            lines.append(f"### {path}")
            for k, v in out[path].items():
                lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)[:400]}")
        return "\n".join(lines) + "\n"
