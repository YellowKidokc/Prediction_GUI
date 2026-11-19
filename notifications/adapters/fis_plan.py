"""Render David-OS plans and record decisions against their exact hashes."""
import json
from shared.review import validate_plan, decision_receipt, digest
from notifications.contract import NotificationItem


def submit_plan(engine, plan):
    validate_plan(plan)
    engine.ledger.conn.execute('CREATE TABLE IF NOT EXISTS fis_plan_imports(plan_hash TEXT PRIMARY KEY, plan_id TEXT, batch_id TEXT, body TEXT)')
    found = engine.ledger.conn.execute('SELECT batch_id FROM fis_plan_imports WHERE plan_hash=?', (plan['hash'],)).fetchone()
    if found:
        return found[0]
    items = []
    for row in plan['rows']:
        items.append(NotificationItem(row['path'], row.get('target', row['path']),
            'Held: ' + row['flag'] if row.get('flag') else 'Explicit review required',
            {'fis_plan_id': plan['id'], 'fis_plan_hash': plan['hash'], 'fis_row_id': row['id'],
             'fis_flag': row.get('flag', ''), 'registry_uuid': row.get('file', {}).get('registry_uuid'),
             'risk_class': 'mutation', 'auto_approvable': False},
            id=digest([plan['hash'], row['id']])))
    batch = engine.submit('approval_batch', 'FIS plan review', plan['root'], 'David-OSv3.fis', items,
                          desktop=False, auto_advise=False)
    engine.ledger.conn.execute('INSERT INTO fis_plan_imports VALUES(?,?,?,?)',
                              (plan['hash'], plan['id'], batch, json.dumps(plan)))
    engine.ledger.conn.commit()
    return batch


def decide(engine, plan, rows, decision, actor, note=''):
    receipt = decision_receipt(plan, rows, decision, actor, note)
    submit_plan(engine, plan)
    ids = [digest([plan['hash'], row]) for row in rows]
    # Existing choices are idempotent only with the same recorded actor/note.
    for key in ids:
        row = engine.ledger.conn.execute('SELECT status FROM notification_items WHERE id=?', (key,)).fetchone()
        if row['status'] != 'pending':
            prior = engine.ledger.conn.execute('SELECT decision,actor,note FROM notification_decisions WHERE item_id=? ORDER BY id DESC LIMIT 1', (key,)).fetchone()
            if prior is None or tuple(prior) != (decision, actor, note):
                raise ValueError('decision conflicts with recorded choice')
    # Persist first; only recorded explicit choices may leave the GUI as receipts.
    engine.store.decide(ids, decision, actor, note)
    actual = {r['id']: r['status'] for r in engine.store.items(
        engine.ledger.conn.execute('SELECT batch_id FROM fis_plan_imports WHERE plan_hash=?', (plan['hash'],)).fetchone()[0])}
    if any(actual.get(key) != decision for key in ids):
        raise ValueError('decision conflicts with a previously recorded choice')
    # Another GUI/API process can win between the initial read and update.
    # Never return a receipt claiming an actor/note that was not recorded.
    for key in ids:
        recorded = engine.ledger.conn.execute('SELECT decision,actor,note FROM notification_decisions WHERE item_id=? ORDER BY id DESC LIMIT 1', (key,)).fetchone()
        if recorded is None or tuple(recorded) != (decision, actor, note):
            raise ValueError('recorded decision differs; reload the review inbox')
    return receipt
