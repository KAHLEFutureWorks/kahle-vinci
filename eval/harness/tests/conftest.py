import sys
from pathlib import Path

HARNESS_EVAL_DIR = Path(__file__).resolve().parents[1]
if str(HARNESS_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_EVAL_DIR))

from _repo_paths import ensure_repo_paths  # noqa: E402

ensure_repo_paths()
