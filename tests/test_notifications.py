import tempfile
import unittest
import csv
from pathlib import Path

from harness.ledger import Ledger
from notifications import NotificationEngine, NotificationItem, NotificationTemplate
from notifications.adapters.naming import read as read_names
from notifications.adapters.atoms import item_from_atom
from notifications.adapters.series_registry import classify as classify_series


class NotificationEngineTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(Path(tempfile.mkdtemp()) / "test.db")
        self.engine = NotificationEngine(self.ledger)

    def test_batch_edit_and_bulk_decision(self):
        batch = self.engine.submit(NotificationTemplate.APPROVAL_BATCH, "Names", "Preview", "test", [
            NotificationItem("old-a.md", "new-a.md", "rename candidate", {"confidence": .95}),
            NotificationItem("old-b.md", "new-b.md", "rename candidate", {"confidence": .72}),
        ], desktop=False, auto_advise=False)
        items = self.engine.store.items(batch)
        self.assertTrue(all(i["status"] == "pending" for i in items))  # confidence cannot authorize mutation
        self.engine.store.set_final_value(items[0]["id"], "edited-a.md")
        self.assertEqual(self.engine.store.items(batch)[0]["final_value"], "edited-a.md")
        self.assertEqual(self.engine.store.decide([i["id"] for i in items], "approved"), 2)
        self.assertTrue(all(i["status"] == "approved" for i in self.engine.store.items(batch)))
        self.assertTrue(all(i["lifecycle_code"] == "RD" for i in self.engine.store.items(batch)))
        self.assertEqual(self.engine.store.reconcile([i["id"] for i in items], note="verified"), 2)
        self.assertTrue(all(i["lifecycle_code"] == "RC" for i in self.engine.store.items(batch)))
        self.assertEqual(self.ledger.conn.execute("SELECT COUNT(*) FROM notification_decisions").fetchone()[0], 4)

    def test_only_explicit_safe_work_auto_approves(self):
        batch = self.engine.submit(NotificationTemplate.APPROVAL_BATCH, "Tags", "Additive", "test", [
            NotificationItem("a.md", "add tag", payload={"confidence": .95, "risk_class": "additive", "auto_approvable": True}),
            NotificationItem("b.md", "rename", payload={"confidence": .99, "risk_class": "mutation", "auto_approvable": True}),
        ], desktop=False, auto_advise=False)
        self.assertEqual([i["status"] for i in self.engine.store.items(batch)], ["approved", "pending"])

    def test_naming_plan_becomes_editable_mutation_rows(self):
        path = Path(tempfile.mkdtemp()) / "names.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("current_path", "proposed_name", "confidence", "reason"))
            writer.writeheader(); writer.writerow({"current_path": "old.md", "proposed_name": "new.md", "confidence": ".98", "reason": "FIS"})
        item = read_names(path)[0]
        self.assertEqual(item.payload["risk_class"], "mutation")
        self.assertFalse(item.payload["auto_approvable"])

    def test_atom_contract_preserves_lean_and_canon_boundaries(self):
        lean = item_from_atom({"schema_version": "atom-universal/1.0", "atom": {
            "id": "L1", "type": "lean", "title": "T", "claim": "C",
            "lean_block": {"compile_status": "success", "zero_sorry": True}},
            "identity": {"source_hash": "sha256:x"}, "nabla": {"confidence": .99}})
        self.assertEqual(lean.payload["risk_class"], "additive")
        self.assertFalse(lean.payload["auto_approvable"])
        canon = item_from_atom({"schema_version": "atom-universal/1.0", "atom": {
            "id": "C1", "type": "claim", "title": "T", "claim": "C",
            "commitment": "Canon", "register": "canon"}})
        self.assertEqual(canon.payload["risk_class"], "canon_authority")

    def test_series_registry_matches_alias_before_proposing_code(self):
        rows = [{"Code":"JSC", "Full series name":"Jesus Coherent Series", "Older aliases":"JS-Series;JSC Series"},
                {"Code":"GOIS", "Full series name":"GOD IS", "Older aliases":"GI production"}]
        self.assertEqual(classify_series("JS-Series", rows)["code"], "JSC")
        proposed = classify_series("Mercy Through Information", rows)
        self.assertEqual(proposed["status"], "new_code_proposed")
        self.assertTrue(3 <= len(proposed["code"]) <= 4)
        self.assertEqual(proposed["lifecycle_code"], "PD")


if __name__ == "__main__":
    unittest.main()
