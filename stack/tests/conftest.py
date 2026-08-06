from __future__ import annotations

import sys
from pathlib import Path

# Die Stack-Tests importieren einzelne Portal- und kb-sync-Module direkt als
# Top-Level-Module (z. B. `backup_restore`, `hybrid_sync`). Dafuer werden die
# beiden Modulverzeichnisse auf den Suchpfad gelegt, nicht deren Paketwurzeln:
# beide Dienste haetten sonst ein konkurrierendes Paket `app`.
STACK_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIRS = (
    STACK_ROOT / "kb-admin-api" / "app",
    STACK_ROOT / "kb-sync" / "app",
)

for module_dir in MODULE_DIRS:
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
