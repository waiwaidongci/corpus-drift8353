"""Convenience entry point for the offline batch proofreading runner.

Usage from anywhere:

    python backend/scripts/batch_compare.py manifest.json \
        --output-dir batch-results

It is equivalent to ``python -m src.batch`` when running from ``backend/``.
"""

from pathlib import Path
import sys

# Allow both `python backend/scripts/batch_compare.py ...` from the repository
# root and `python scripts/batch_compare.py ...` from backend/.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.batch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
