import hmac
import hashlib
import os
from typing import Optional

API_KEY = os.getenv("TOOL_API_KEY", "")

def require_api_key(provided: Optional[str]) -> None:
    # Simple shared secret (good MVP). Later: JWT or OWUI user passthrough.
    if not API_KEY:
        return  # allow if unset (dev only)
    if not provided or not hmac.compare_digest(provided, API_KEY):
        raise PermissionError("Unauthorized")

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
