from __future__ import annotations

import sys
from pathlib import Path

# Die Tests importieren das Portal-Backend als Paket `app`. Im Container liegt
# dieses unter /app; lokal muss der Paketwurzelpfad explizit gesetzt werden,
# damit die Suite unabhaengig vom Arbeitsverzeichnis laeuft.
SERVICE_ROOT = Path(__file__).resolve().parents[1]

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
