"""
Zeitmessung fuer den RTO-Nachweis aus Abschnitt 25 und 29.5 des PRD.

Der Korrektheitsnachweis des Restores liegt in
``test_portal_restore_reindex_e2e.py``. Dieses Skript ergaenzt die im
Abnahmeprotokoll geforderte Zeitmessung: Es erzeugt einen Portalbestand in
realistischer Groesse, sichert ihn verschluesselt, stellt ihn wieder her und
baut den Hybridindex vollstaendig neu auf. Gemessen wird jeder Schritt.

Aufruf aus stack/:

    python tests/measure_restore_rto.py --documents 500

Das Skript ist kein Test. Es schreibt ausschliesslich in ein temporaeres
Verzeichnis und laesst den laufenden Stack unberuehrt.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

STACK_ROOT = Path(__file__).resolve().parents[1]
for module_dir in (STACK_ROOT / "kb-admin-api" / "app", STACK_ROOT / "kb-sync" / "app"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from backup_restore import create_backup, restore_backup, validate_restored_portal  # noqa: E402
from canonical_inventory import load_portal_inventory  # noqa: E402
from hybrid_sync import HybridIndexBuilder  # noqa: E402

RTO_SECONDS = 4 * 60 * 60
TODAY = date(2026, 8, 6)

# Ein Abschnitt in der Groessenordnung echter KAHLE-Arbeitsanweisungen, damit
# Chunking und Embedding nicht auf unrealistisch kurzem Text gemessen werden.
PARAGRAPH = (
    "Eine Garantieanfrage wird ueber den beschriebenen Serviceprozess eingereicht. "
    "Die zustaendige Fachabteilung prueft die Angaben auf Vollstaendigkeit und "
    "dokumentiert das Ergebnis im Vorgang. Abweichungen werden begruendet. "
)


class MemoryQdrant:
    """Nimmt Punkte entgegen, ohne Netzwerklatenz in die Messung zu tragen."""

    def __init__(self) -> None:
        self.staging = ""
        self.points: list[dict] = []
        self.alias = ""

    def create_staging(self, name: str) -> None:
        self.staging = name

    def upsert(self, collection: str, points: list[dict]) -> None:
        self.points.extend(points)

    def activate_alias(self, alias: str, staging: str) -> None:
        self.alias = alias


class DeterministicEmbeddings:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 17), float(text.count("Service")), 1.0] for text in texts]


@contextmanager
def measured(label: str, results: dict[str, float]):
    start = time.perf_counter()
    yield
    results[label] = time.perf_counter() - start


def build_portal(root: Path, documents: int, sections: int, original_kb: int) -> Path:
    portal = root / "portal-data"
    portal.mkdir(parents=True)
    db = sqlite3.connect(portal / "wissensportal.sqlite3")
    db.executescript(
        """
        CREATE TABLE portal_users(user_id TEXT PRIMARY KEY,email TEXT);
        CREATE TABLE canonical_documents(
          document_id TEXT PRIMARY KEY,title TEXT,owner_user_id TEXT,confidentiality TEXT,active_version_id TEXT
        );
        CREATE TABLE document_metadata(
          document_id TEXT PRIMARY KEY,authority_type TEXT,authority_level INTEGER,scope_json TEXT
        );
        CREATE TABLE document_versions(
          version_id TEXT PRIMARY KEY,document_id TEXT,status TEXT,valid_from TEXT,valid_until TEXT
        );
        CREATE TABLE document_publications(document_id TEXT,knowledgebase_id TEXT,status TEXT);
        INSERT INTO portal_users VALUES ('owner','owner@kahle.de');
        """
    )
    for index in range(documents):
        document_id, version_id = f"doc-{index:05d}", f"version-{index:05d}"
        body = "\n\n".join(
            f"## Abschnitt {section}\n\n{PARAGRAPH}" for section in range(1, sections + 1)
        )
        files = portal / "files" / document_id / version_id
        files.mkdir(parents=True)
        # Originale sind PDF und DOCX, also praktisch nicht komprimierbar.
        # Zufallsbytes bilden das fuer Backup und Restore realistisch ab.
        (files / "original.bin").write_bytes(os.urandom(original_kb * 1024))
        (files / "rag.md").write_text(f"# Prozess {index}\n\n{body}\n", encoding="utf-8")
        db.execute(
            "INSERT INTO canonical_documents VALUES (?,?,?,?,?)",
            (document_id, f"Prozess {index}", "owner", "restricted", version_id),
        )
        db.execute(
            "INSERT INTO document_metadata VALUES (?,?,?,?)",
            (document_id, "process_instruction", 5, "{}"),
        )
        db.execute(
            "INSERT INTO document_versions VALUES (?,?,?,?,?)",
            (version_id, document_id, "active", "2026-08-06", "2099-12-31"),
        )
        db.execute(
            "INSERT INTO document_publications VALUES (?,?,?)",
            (document_id, "service", "active"),
        )
    db.commit()
    db.close()
    return portal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=500)
    parser.add_argument("--sections", type=int, default=12)
    parser.add_argument("--original-kb", type=int, default=800,
                        help="Groesse je Originaldatei in KB (typisches DOCX/PDF)")
    args = parser.parse_args()

    results: dict[str, float] = {}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with measured("Bestand erzeugen", results):
            portal = build_portal(root / "source", args.documents, args.sections, args.original_kb)
        payload_bytes = sum(f.stat().st_size for f in portal.rglob("*") if f.is_file())

        key = os.urandom(32)
        backup = root / "backup" / "rto.kahlebackup"
        with measured("Verschluesseltes Backup", results):
            created = create_backup({"portal-data": portal}, backup, key)

        restored = root / "restored"
        with measured("Restore", results):
            restore_backup(backup, restored, key)
        with measured("Validierung", results):
            validate_restored_portal(restored)

        with measured("Inventar laden", results):
            inventory = load_portal_inventory(
                restored / "portal-data" / "wissensportal.sqlite3",
                restored / "portal-data" / "files",
                today=TODAY,
            )

        qdrant = MemoryQdrant()
        with measured("Hybridindex neu aufbauen", results):
            report = HybridIndexBuilder(
                qdrant, DeterministicEmbeddings(), alias="vinci_rto",
                snapshot_path=root / "bm25.json",
            ).rebuild(list(inventory.documents), today=TODAY)

        if len(inventory.documents) != args.documents:
            print(f"FEHLER: {len(inventory.documents)} statt {args.documents} Dokumenten "
                  "wiederhergestellt")
            return 1

        total = sum(results.values())
        recovery = total - results["Bestand erzeugen"]

        print(f"Dokumente:            {args.documents}")
        print(f"Gesicherte Dateien:   {created.files}")
        print(f"Nutzdaten:            {payload_bytes / 1024 / 1024:.1f} MB")
        print(f"Backupdatei:          {backup.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"Indexierte Chunks:    {report['chunks']}")
        print()
        for label, seconds in results.items():
            print(f"  {label:<26} {seconds:8.2f} s")
        print(f"  {'Wiederherstellung gesamt':<26} {recovery:8.2f} s")
        print()
        print(f"RTO-Budget: {RTO_SECONDS} s. Ausgeschoepft: {recovery / RTO_SECONDS * 100:.2f} %")
        if recovery > RTO_SECONDS:
            print("RTO VERFEHLT")
            return 1
        print("RTO EINGEHALTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
