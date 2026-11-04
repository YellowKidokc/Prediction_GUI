import tempfile
import unittest
import csv
from pathlib import Path

from harness.ledger import Ledger
from notifications import NotificationEngine, NotificationItem, NotificationTemplate
from notifications.adapters.naming import read as read_names


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
        self.assertEqual(self.ledger.conn.execute("SELECT COUNT(*) FROM notification_decisions").fetchone()[0], 2)

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


if __name__ == "__main__":
    unittest.main()
