"""Localhost JSON API for the notification and approval engine."""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.runner import Runner  # noqa: E402
from notifications import NotificationEngine, NotificationItem  # noqa: E402
from notifications.adapters.atoms import item_from_atom  # noqa: E402
from notifications.adapters.series_registry import submit as submit_series  # noqa: E402
from API.validation import decision as validate_decision, notification as validate_notification  # noqa: E402

ENGINE = NotificationEngine(Runner().ledger)
MAX_BODY = 10 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, body) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def data(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY: raise ValueError("request exceeds 10 MiB")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/health": return self.reply(200, {"ok": True, "service": "prediction-notifications", "version": "1"})
        if self.path == "/v1/batches": return self.reply(200, {"batches": ENGINE.store.batches()})
        match = re.fullmatch(r"/v1/batches/([0-9a-f]+)/items", self.path)
        if match: return self.reply(200, {"items": ENGINE.store.items(match.group(1))})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self.data()
            if self.path == "/v1/atoms/review":
                item = item_from_atom(body)
                batch_id = ENGINE.submit("approval_batch", f"Atom review: {item.subject}",
                                         "Imported through Universal Atom API Contract v1.0.",
                                         "Faith-through-physics-atoms", [item])
                return self.reply(201, {"batch_id": batch_id, "items": 1})
            if self.path == "/v1/series/classify":
                names = body.get("names") or []
                if not isinstance(names, list) or not names: raise ValueError("names must be a non-empty list")
                batch_id = submit_series(ENGINE, [str(name) for name in names])
                return self.reply(201, {"batch_id": batch_id, "items": len(names)})
            if self.path == "/v1/notifications":
                validate_notification(body)
                items = [NotificationItem(
                    subject=i["subject"], proposed_action=i["proposed_action"],
                    summary=i.get("reason", ""), payload={
                        "current_value": i.get("current_value", i["subject"]),
                        "confidence": i.get("confidence"), "risk_class": i.get("risk_class", "mutation"),
                        "auto_approvable": bool(i.get("auto_approvable", False)),
                        "evidence": i.get("evidence"), "metadata": i.get("metadata", {})})
                    for i in body["items"]]
                batch_id = ENGINE.submit(body["template"], body["title"], body.get("message", ""),
                                         body["source"], items, body.get("severity", "normal"))
                return self.reply(201, {"batch_id": batch_id, "items": len(items)})
            if self.path == "/v1/decisions":
                validate_decision(body)
                changed = ENGINE.store.decide(body["item_ids"], body["decision"],
                                              body.get("actor", "API user"), body.get("note", ""))
                return self.reply(200, {"changed": changed})
            if self.path == "/v1/reconcile":
                item_ids = body.get("item_ids") or []
                if not isinstance(item_ids, list) or not item_ids: raise ValueError("item_ids must be a non-empty list")
                changed = ENGINE.store.reconcile(item_ids, body.get("actor", "executor"), body.get("note", ""))
                return self.reply(200, {"changed": changed, "lifecycle_code": "RC"})
            match = re.fullmatch(r"/v1/batches/([0-9a-f]+)/advise", self.path)
            if match: return self.reply(200, {"advice": ENGINE.request_advice(match.group(1))})
            self.reply(404, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(503, {"error": str(exc), "changed": False})

    def log_message(self, fmt, *args):
        print(f"API {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    port = int(os.environ.get("PREDICTION_API_PORT", "2831"))
    print(f"Prediction notification API: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
