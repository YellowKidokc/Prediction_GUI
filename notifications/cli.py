"""Portable notification engine CLI."""
from __future__ import annotations

import argparse
import json

from harness.runner import Runner
from .contract import NotificationItem, NotificationTemplate
from .engine import NotificationEngine


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo"); demo.add_argument("--no-desktop", action="store_true")
    sub.add_parser("list")
    decide = sub.add_parser("decide"); decide.add_argument("decision", choices=("approved", "held", "rejected", "answered")); decide.add_argument("item_ids", nargs="+")
    advice = sub.add_parser("advise"); advice.add_argument("batch_id")
    names = sub.add_parser("import-names"); names.add_argument("plan"); names.add_argument("--no-desktop", action="store_true")
    args = p.parse_args()
    engine = NotificationEngine(Runner().ledger)
    if args.command == "demo":
        print(engine.submit(NotificationTemplate.APPROVAL_BATCH, "Review proposed changes",
              "Simulation only; no files have changed.", "demo",
              [NotificationItem("example.md", "rename", "old.md -> proposed.md")],
              desktop=not args.no_desktop))
    elif args.command == "list":
        print(json.dumps(engine.store.batches(), indent=2))
    elif args.command == "decide":
        print(engine.store.decide(args.item_ids, args.decision))
    elif args.command == "advise":
        print(engine.request_advice(args.batch_id))
    elif args.command == "import-names":
        from .adapters.naming import submit
        print(submit(engine, args.plan, desktop=not args.no_desktop))


if __name__ == "__main__":
    main()
