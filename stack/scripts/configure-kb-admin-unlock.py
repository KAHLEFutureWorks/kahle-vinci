#!/usr/bin/env python3
"""Configure the KAHLE/VECTOR second admin gate without exposing the code."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import os
import secrets
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path

ITERATIONS = 600_000
KEYS = (
    "KB_ADMIN_UNLOCK_CODE_HASH",
    "KB_ADMIN_UNLOCK_SESSION_SECRET",
    "KB_ADMIN_UNLOCK_TTL_SECONDS",
    "KB_ADMIN_UNLOCK_MAX_ATTEMPTS",
    "KB_ADMIN_UNLOCK_BLOCK_SECONDS",
)


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def prompt_code() -> str:
    first = getpass.getpass("Neuen KAHLE/VECTOR-Sicherheitscode eingeben: ")
    if len(first) < 8:
        raise SystemExit("Der Sicherheitscode muss mindestens 8 Zeichen lang sein.")
    second = getpass.getpass("Sicherheitscode wiederholen: ")
    if first != second:
        raise SystemExit("Die Eingaben stimmen nicht überein.")
    return first


def update_env(path: Path, values: dict[str, str]) -> Path:
    if not path.is_file():
        raise SystemExit(f"Produktions-ENV nicht gefunden: {path}")
    original_stat = path.stat()
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in values:
            output.append(f"{key}={values[key]}")
            replaced.add(key)
        else:
            output.append(line)
    if replaced != set(values):
        output.extend(["", "# KAHLE/VECTOR second admin gate"])
        for key in KEYS:
            if key not in replaced:
                output.append(f"{key}={values[key]}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write("\n".join(output).rstrip() + "\n")
        temporary = Path(handle.name)
    os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
    if hasattr(os, "chown"):
        os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
    os.replace(temporary, path)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file",
        default="/opt/kahle-vinci/stack/.env.production",
        help="Path to the production environment file",
    )
    args = parser.parse_args()
    code = prompt_code()
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ITERATIONS)
    values = {
        "KB_ADMIN_UNLOCK_CODE_HASH": f"pbkdf2_sha256.{ITERATIONS}.{b64url(salt)}.{b64url(digest)}",
        "KB_ADMIN_UNLOCK_SESSION_SECRET": secrets.token_urlsafe(64),
        "KB_ADMIN_UNLOCK_TTL_SECONDS": "28800",
        "KB_ADMIN_UNLOCK_MAX_ATTEMPTS": "5",
        "KB_ADMIN_UNLOCK_BLOCK_SECONDS": "900",
    }
    backup = update_env(Path(args.env_file).resolve(), values)
    print("KAHLE/VECTOR-Zusatzsperre wurde sicher konfiguriert.")
    print(f"Backup: {backup}")
    print("Der Sicherheitscode wurde nicht gespeichert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())