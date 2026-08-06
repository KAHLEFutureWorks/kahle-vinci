from __future__ import annotations

import sys
from pathlib import Path

# kb-sync besitzt ein eigenes Paket `app`. Es darf nicht gemeinsam mit dem
# gleichnamigen Paket des Portal-Backends in denselben Prozess geladen werden;
# der lokale Testrunner faehrt die Suiten deshalb getrennt.
SERVICE_ROOT = Path(__file__).resolve().parents[1]

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
