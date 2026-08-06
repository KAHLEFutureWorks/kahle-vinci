from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"KAHLEBACKUP1\n"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupResult:
    path: Path
    sha256: str
    files: int
    created_at: str


def decode_key(value: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise BackupError("invalid_backup_key") from exc
    if len(key) != 32:
        raise BackupError("backup_key_must_be_32_bytes")
    return key


def _safe_files(roots: dict[str, Path]) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for label, root in sorted(roots.items()):
        if not root.exists():
            continue
        resolved = root.resolve()
        for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
            path.resolve().relative_to(resolved)
            files.append((f"{label}/{path.relative_to(resolved).as_posix()}", path))
    return files


def create_backup(roots: dict[str, Path], destination: Path, key: bytes) -> BackupResult:
    files = _safe_files(roots)
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "format": 1, "created_at": created_at,
        "files": {name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
                  for name, path in files},
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        encoded = json.dumps(manifest, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("manifest.json"); info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))
        for name, path in files:
            archive.add(path, arcname=name, recursive=False)
    nonce = os.urandom(12)
    encrypted = AESGCM(key).encrypt(nonce, stream.getvalue(), MAGIC)
    payload = MAGIC + nonce + encrypted
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return BackupResult(destination, hashlib.sha256(payload).hexdigest(), len(files), created_at)


def restore_backup(backup: Path, destination: Path, key: bytes) -> dict:
    payload = backup.read_bytes()
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 13:
        raise BackupError("invalid_backup_format")
    plaintext = AESGCM(key).decrypt(
        payload[len(MAGIC):len(MAGIC) + 12], payload[len(MAGIC) + 12:], MAGIC,
    )
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise BackupError("restore_destination_not_empty")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as archive:
            for member in archive.getmembers():
                target = (staging / member.name).resolve()
                target.relative_to(staging.resolve())
                if member.issym() or member.islnk():
                    raise BackupError("backup_links_not_allowed")
            archive.extractall(staging, filter="data")
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            path = staging / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
                raise BackupError(f"backup_integrity_failed:{name}")
        for item in staging.iterdir():
            if item.name != "manifest.json":
                shutil.move(str(item), destination / item.name)
    return manifest


def validate_restored_portal(destination: Path) -> None:
    databases = list((destination / "portal-data").glob("*.sqlite3"))
    if len(databases) != 1:
        raise BackupError("portal_database_missing")
    connection = sqlite3.connect(databases[0])
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError("portal_database_integrity_failed")
        active = connection.execute(
            "SELECT document_id, active_version_id FROM canonical_documents WHERE active_version_id IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()
    for document_id, version_id in active:
        if not (destination / "portal-data" / "files" / document_id / version_id / "rag.md").is_file():
            raise BackupError(f"active_markdown_missing:{version_id}")
