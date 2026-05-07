"""
title: KAHLE Knowledgebase Diagnose
author: local
version: 0.1.0
description: Admin-Tool zur Diagnose von kb-sync, Qdrant Collections und Knowledgebase-Dateien.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_COLLECTIONS = ("kahleallgemein", "kahlekontext", "kahlerichtlinien")
DEFAULT_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".csv")


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _collections() -> list[str]:
    raw = _env("KB_SYNC_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS))
    return [item.strip() for item in raw.split(",") if item.strip()]


def _supported_extensions() -> tuple[str, ...]:
    raw = _env("KB_SYNC_EXTENSIONS", ",".join(DEFAULT_EXTENSIONS))
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _qdrant_url() -> str:
    return _env("QDRANT_URL", _env("QDRANT_URI", "http://qdrant:6333")).rstrip("/")


def _kb_root() -> Path:
    return Path(_env("KB_ROOT", "/knowledgebases"))


def _state_path() -> Path:
    return Path(_env("KB_STATE_PATH", "/kb-sync-state/kb-sync-state.json"))


def _request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    response = requests.request(method, url, timeout=30, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} -> {response.status_code}: {response.text[:300]}")
    if not response.text:
        return {}
    return response.json()


def _collection_exists(qdrant_url: str, collection: str) -> bool:
    response = requests.get(f"{qdrant_url}/collections/{collection}", timeout=30)
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {collection} -> {response.status_code}: {response.text[:300]}")
    return True


def _qdrant_count(qdrant_url: str, collection: str) -> int:
    body = _request_json("POST", f"{qdrant_url}/collections/{collection}/points/count", json={"exact": True})
    return int(((body.get("result") or {}).get("count")) or 0)


def _scroll_docs(qdrant_url: str, collection: str, max_points: int = 10000) -> dict[str, Any]:
    offset: Any = None
    scanned = 0
    docs: dict[str, dict[str, Any]] = {}
    truncated = False
    while True:
        body: dict[str, Any] = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        result = _request_json("POST", f"{qdrant_url}/collections/{collection}/points/scroll", json=body).get("result") or {}
        for point in result.get("points") or []:
            scanned += 1
            payload = point.get("payload") or {}
            doc_id = str(payload.get("doc_id") or "")
            source_path = str(payload.get("source_path") or "")
            if not doc_id and source_path:
                doc_id = f"{collection}/{source_path}"
            if not doc_id:
                doc_id = str(point.get("id") or "")
            item = docs.setdefault(
                doc_id,
                {
                    "doc_id": doc_id,
                    "source_path": source_path,
                    "chunks": 0,
                    "sample_chunk_indexes": [],
                },
            )
            item["chunks"] += 1
            chunk_index = payload.get("chunk_index")
            if len(item["sample_chunk_indexes"]) < 5 and chunk_index is not None:
                item["sample_chunk_indexes"].append(chunk_index)
            if scanned >= max_points:
                truncated = True
                break
        if truncated:
            break
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return {"scanned_points": scanned, "docs": docs, "truncated": truncated}


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"exists": False, "path": str(path), "data": {"collections": {}}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": str(exc), "data": {"collections": {}}}
    if not isinstance(data, dict):
        data = {"collections": {}}
    data.setdefault("collections", {})
    return {"exists": True, "path": str(path), "data": data}


def _fs_files(collection: str) -> dict[str, dict[str, Any]]:
    root = _kb_root() / collection
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    extensions = _supported_extensions()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        result[rel] = {"source_path": rel, "size_bytes": int(stat.st_size), "mtime": int(stat.st_mtime)}
    return result


def _collection_report(collection: str) -> dict[str, Any]:
    qurl = _qdrant_url()
    state = _load_state()
    state_collection = ((state.get("data") or {}).get("collections") or {}).get(collection) or {}
    state_files = state_collection.get("files") or {}
    filesystem_files = _fs_files(collection)
    exists = _collection_exists(qurl, collection)
    qdrant_docs: dict[str, dict[str, Any]] = {}
    point_count = 0
    truncated = False
    if exists:
        point_count = _qdrant_count(qurl, collection)
        scrolled = _scroll_docs(qurl, collection)
        qdrant_docs = scrolled["docs"]
        truncated = bool(scrolled["truncated"])

    fs_doc_ids = {f"{collection}/{path}" for path in filesystem_files}
    state_doc_ids = {f"{collection}/{path}" for path in state_files}
    qdrant_doc_ids = set(qdrant_docs)

    missing_in_qdrant = sorted(fs_doc_ids - qdrant_doc_ids)
    orphan_in_qdrant = sorted(qdrant_doc_ids - fs_doc_ids)
    missing_in_state = sorted(fs_doc_ids - state_doc_ids)
    state_without_file = sorted(state_doc_ids - fs_doc_ids)

    files = []
    for rel_path, fs_info in filesystem_files.items():
        doc_id = f"{collection}/{rel_path}"
        state_info = state_files.get(rel_path) or {}
        q_info = qdrant_docs.get(doc_id) or {}
        files.append(
            {
                "source_path": rel_path,
                "doc_id": doc_id,
                "size_bytes": fs_info["size_bytes"],
                "state_chunks": state_info.get("chunks"),
                "qdrant_chunks": q_info.get("chunks", 0),
                "state_updated_at": state_info.get("updated_at", ""),
                "indexed": bool(q_info.get("chunks")),
            }
        )

    return {
        "collection": collection,
        "qdrant_collection_exists": exists,
        "qdrant_points": point_count,
        "qdrant_docs": len(qdrant_doc_ids),
        "filesystem_files": len(filesystem_files),
        "state_files": len(state_files),
        "last_reconcile_at": state_collection.get("last_reconcile_at", ""),
        "state_path": state.get("path"),
        "state_exists": state.get("exists"),
        "truncated": truncated,
        "issues": {
            "missing_in_qdrant": missing_in_qdrant[:50],
            "orphan_in_qdrant": orphan_in_qdrant[:50],
            "missing_in_state": missing_in_state[:50],
            "state_without_file": state_without_file[:50],
        },
        "files": files[:200],
    }


class Tools:
    async def kb_status(self, collection: str = "") -> str:
        """
        Erstellt einen Admin-Statusbericht fuer eine oder alle KAHLE Knowledgebase-Collections.

        :param collection: Optional kahleallgemein, kahlekontext oder kahlerichtlinien. Leer = alle Collections.
        """
        try:
            selected = [collection.strip()] if collection.strip() else _collections()
            reports = [_collection_report(name) for name in selected]
            summary = {
                "ok": True,
                "qdrant_url": _qdrant_url(),
                "kb_root": str(_kb_root()),
                "state_path": str(_state_path()),
                "collections": [
                    {
                        "collection": item["collection"],
                        "qdrant_points": item["qdrant_points"],
                        "qdrant_docs": item["qdrant_docs"],
                        "filesystem_files": item["filesystem_files"],
                        "state_files": item["state_files"],
                        "last_reconcile_at": item["last_reconcile_at"],
                        "issue_counts": {key: len(value) for key, value in item["issues"].items()},
                    }
                    for item in reports
                ],
                "reports": reports,
            }
            return _json(summary)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kb_file_status(self, collection: str, filename_contains: str) -> str:
        """
        Prueft eine Datei oder einen Dateinamen-Ausschnitt in einer Knowledgebase.

        :param collection: Collection-Name, z. B. kahleallgemein.
        :param filename_contains: Teil des Dateinamens oder Pfads.
        """
        try:
            needle = str(filename_contains or "").strip().lower()
            if not needle:
                raise ValueError("filename_contains darf nicht leer sein")
            report = _collection_report(collection.strip())
            matches = [item for item in report["files"] if needle in item["source_path"].lower()]
            return _json(
                {
                    "ok": True,
                    "collection": collection,
                    "filename_contains": filename_contains,
                    "matches": matches,
                    "count": len(matches),
                    "last_reconcile_at": report["last_reconcile_at"],
                }
            )
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kb_reindex_hint(self, collection: str = "") -> str:
        """
        Gibt sichere Hinweise, wie eine Knowledgebase neu indiziert werden kann. Fuehrt keinen Reindex aus.

        :param collection: Optional Collection-Name.
        """
        selected = collection.strip() or "alle Collections"
        return _json(
            {
                "ok": True,
                "collection": selected,
                "note": "Dieses Tool fuehrt keinen Reindex aus. kb-sync reconciled automatisch alle 300 Sekunden und bei Dateiaenderungen.",
                "manual_checks": [
                    "Containerstatus pruefen: docker ps --filter name=kb-sync",
                    "Logs pruefen: docker logs --tail 100 kb-sync",
                    "Qdrant Count pruefen: POST http://127.0.0.1:6333/collections/<collection>/points/count",
                    "Wenn Qdrant geloescht wurde: kb-sync erkennt leere Collection bei vorhandener State-Datei und erzwingt Reindex.",
                ],
            }
        )
