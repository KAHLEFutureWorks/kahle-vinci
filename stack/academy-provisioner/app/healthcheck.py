from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .state import SQLiteProvisioningStateStore


def health_status(
    state: SQLiteProvisioningStateStore,
    *,
    now_epoch: int,
    max_age_seconds: int = 120,
) -> int:
    heartbeat = state.heartbeat_epoch()
    if heartbeat is None or now_epoch - heartbeat > max_age_seconds:
        return 1
    return 0


def main() -> int:
    state = SQLiteProvisioningStateStore(
        Path(os.getenv("LEARNINGSUITE_STATE_DB_PATH", "/state/provisioning.sqlite3"))
    )
    return health_status(state, now_epoch=int(time.time()))


if __name__ == "__main__":
    sys.exit(main())
