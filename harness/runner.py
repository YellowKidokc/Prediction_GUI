"""GUI adapter: preserve this application's ledger path; David-OS owns inference."""
from pathlib import Path
from prediction.runner import Runner as _Runner
DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'harness.db'
class Runner(_Runner):
    def __init__(self, db_path=DB_PATH, context_keys=('channel',)):
        super().__init__(db_path=db_path, context_keys=context_keys)
