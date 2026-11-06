import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"   # force DeepSeek offline -> rule fallback
os.environ["DEEPSEEK_BACKEND"] = "ollama"

from nlp import pipeline  # noqa: E402


class NLPPipelineTests(unittest.TestCase):
    def setUp(self):
        pipeline.DATA = Path(tempfile.mkdtemp())
        self.folder = Path(tempfile.mkdtemp())
        note = "---\ntitle: Grace\n---\n# Grace\nGrace acts like curvature. See [[Law 1]] #law.\n"
        (self.folder / "a.md").write_text(note); (self.folder / "b.md").write_text(note)
        (self.folder / "c.txt").write_text("Shannon capacity grows with signal over noise.")

    def test_plan_run_lock_cycle(self):
        p = pipeline.Pipeline("t")
        v = p.plan(str(self.folder), "find duplicates")
        self.assertEqual(v["plan"]["planner"], "rules")
        res = p.run()
        self.assertTrue((res / "report.md").exists())
        import json
        out = json.loads((res / "results.json").read_text())
        self.assertEqual(out["_corpus"]["near_duplicates"][0]["jaccard"], 1.0)
        self.assertNotIn("title", out["a.md"]["keywords"])   # frontmatter excluded
        self.assertEqual(out["a.md"]["markdown_structure"]["wikilinks"], ["Law 1"])
        p.set_plan({"steps": [{"step": "stats"}, {"step": "made_up"}]})
        self.assertEqual([s["step"] for s in p.current["plan"]["steps"]], ["stats"])
        self.assertEqual(p.lock(), 2)
        with self.assertRaises(RuntimeError):
            p.revise("anything")
        self.assertEqual(pipeline.Pipeline("t").current["v"], 2)  # persisted


if __name__ == "__main__":
    unittest.main()
