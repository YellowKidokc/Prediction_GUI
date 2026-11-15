import copy
import tempfile
import unittest
from pathlib import Path
from harness.ledger import Ledger
from notifications import NotificationEngine
from notifications.adapters.fis_plan import submit_plan, decide
from shared.review import digest
from shared.meq_namer import meq_namer_string


class FISReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'review.sqlite'
        self.ledger = Ledger(self.db); self.addCleanup(self.ledger.conn.close)
        self.engine = NotificationEngine(self.ledger)
        self.plan = {'id':'test-plan', 'root':self.temp.name, 'rows':[
            {'id':'r1', 'path':'old.md', 'target':'new.md', 'flag':''},
            {'id':'held', 'path':'held.md', 'target':'other.md', 'flag':'collision'}]}
        self.plan['hash'] = digest(self.plan)

    def test_exact_receipt_and_restart(self):
        batch = submit_plan(self.engine, self.plan)
        self.assertEqual(batch, submit_plan(self.engine, self.plan))
        receipt = decide(self.engine, self.plan, ['r1'], 'approved', 'David')
        reopened = Ledger(self.db); self.addCleanup(reopened.conn.close)
        second = NotificationEngine(reopened)
        self.assertEqual(receipt, decide(second, self.plan, ['r1'], 'approved', 'David'))
        self.assertEqual(second.store.items(batch)[0]['status'], 'approved')
        with self.assertRaises(ValueError): decide(second, self.plan, ['r1'], 'approved', 'someone else')
        self.assertTrue(meq_namer_string({'G':3}).startswith('G3 M0'))

    def test_receipt_cannot_claim_a_competing_actors_choice(self):
        from unittest.mock import patch
        original_decide = self.engine.store.decide
        def competing(ids, decision, actor, note):
            return original_decide(ids, decision, 'other recorded actor', note)
        with patch.object(self.engine.store, 'decide', side_effect=competing):
            with self.assertRaisesRegex(ValueError, 'recorded decision differs'):
                decide(self.engine, self.plan, ['r1'], 'approved', 'David')

    def test_edits_holds_and_modified_plan_cannot_approve(self):
        batch = submit_plan(self.engine, self.plan)
        with self.assertRaises(ValueError): decide(self.engine, self.plan, ['held'], 'approved', 'David')
        self.engine.store.set_final_value(self.engine.store.items(batch)[0]['id'], 'edited.md')
        with self.assertRaises(ValueError): decide(self.engine, self.plan, ['r1'], 'approved', 'David')
        bad = copy.deepcopy(self.plan); bad['rows'][0]['target'] = 'tampered.md'
        with self.assertRaises(ValueError): submit_plan(self.engine, bad)
        self.assertTrue(all(i['status']=='pending' for i in self.engine.store.items(batch)))


if __name__ == '__main__': unittest.main()
