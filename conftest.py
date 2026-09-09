"""Put the repo root on sys.path so tests can import `backend.*` and `ingest.*`.

Matches how the app runs (PYTHONPATH=/app in the container), so tests and production
resolve imports identically.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
