import os
import time
import uuid
from pathlib import Path
from typing import Tuple

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data")).resolve()
TTL_HOURS = int(os.getenv("TTL_HOURS", "24"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "30"))

def ensure_storage() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

def _now() -> int:
    return int(time.time())

def save_temp_file(filename: str, content: bytes) -> Tuple[str, Path]:
    ensure_storage()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"File too large (> {MAX_FILE_MB} MB).")
    file_id = str(uuid.uuid4())
    safe_name = filename.replace("/", "_").replace("\\", "_")
    path = STORAGE_DIR / f"{file_id}__{safe_name}"
    path.write_bytes(content)
    return file_id, path

def cleanup_expired() -> int:
    ensure_storage()
    deleted = 0
    ttl_seconds = TTL_HOURS * 3600
    cutoff = _now() - ttl_seconds
    for p in STORAGE_DIR.glob("*__*"):
        try:
            if int(p.stat().st_mtime) < cutoff:
                p.unlink(missing_ok=True)
                deleted += 1
        except Exception:
            # never crash cleanup
            pass
    return deleted
