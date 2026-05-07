from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from docx import Document
from pypdf import PdfReader
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


EMBEDDING_DIMENSION = 1024
DEFAULT_COLLECTIONS = ("kahleallgemein", "kahlekontext", "kahlerichtlinien")
DEFAULT_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".csv")


@dataclass(frozen=True)
class Config:
    kb_root: Path
    state_path: Path
    qdrant_url: str
    ionos_base_url: str
    ionos_api_key: str
    embedding_model: str
    collections: tuple[str, ...]
    debounce_seconds: float
    reconcile_interval_seconds: int
    supported_extensions: tuple[str, ...]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_config() -> Config:
    api_key = env("IONOS_API_KEY")
    if not api_key:
        raise RuntimeError("IONOS_API_KEY is required")

    collections = tuple(
        item.strip()
        for item in env("KB_SYNC_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS)).split(",")
        if item.strip()
    )
    if not collections:
        raise RuntimeError("KB_SYNC_COLLECTIONS must contain at least one collection")

    extensions = tuple(
        item.strip().lower()
        for item in env("KB_SYNC_EXTENSIONS", ",".join(DEFAULT_EXTENSIONS)).split(",")
        if item.strip()
    )

    return Config(
        kb_root=Path(env("KB_ROOT", "/knowledgebases")),
        state_path=Path(env("KB_STATE_PATH", "/state/kb-sync-state.json")),
        qdrant_url=env("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
        ionos_base_url=env("IONOS_OPENAI_BASE_URL", "https://openai.inference.de-txl.ionos.com/v1").rstrip("/"),
        ionos_api_key=api_key,
        embedding_model=env("IONOS_EMBEDDING_MODEL", "BAAI/bge-m3"),
        collections=collections,
        debounce_seconds=float(env("KB_SYNC_DEBOUNCE_SECONDS", "2")),
        reconcile_interval_seconds=int(env("KB_SYNC_RECONCILE_INTERVAL_SECONDS", "300")),
        supported_extensions=extensions,
    )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.data: dict[str, dict[str, Any]] = {"collections": {}}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"state_load_failed path={self.path} error={exc}", flush=True)
            return
        if isinstance(loaded, dict):
            self.data = loaded
            self.data.setdefault("collections", {})

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def collection(self, name: str) -> dict[str, Any]:
        collections = self.data.setdefault("collections", {})
        collection = collections.setdefault(name, {})
        collection.setdefault("files", {})
        return collection


class QdrantClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, timeout=60, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {url} -> {response.status_code}: {response.text[:300]}")
        if not response.text:
            return {}
        return response.json()

    def ensure_collection(self, collection: str) -> None:
        response = requests.put(
            f"{self.base_url}/collections/{collection}",
            json={"vectors": {"size": EMBEDDING_DIMENSION, "distance": "Cosine"}},
            timeout=60,
        )
        if response.status_code not in {200, 409}:
            raise RuntimeError(f"PUT {self.base_url}/collections/{collection} -> {response.status_code}: {response.text[:300]}")

    def count(self, collection: str) -> int:
        result = self.request("POST", f"/collections/{collection}/points/count", json={"exact": True})
        return int(((result.get("result") or {}).get("count")) or 0)

    def delete_document(self, collection: str, doc_id: str) -> None:
        self.request(
            "POST",
            f"/collections/{collection}/points/delete?wait=true",
            json={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}},
        )

    def scroll_doc_ids(self, collection: str) -> set[str]:
        doc_ids: set[str] = set()
        offset: Any = None
        while True:
            body: dict[str, Any] = {"limit": 256, "with_payload": ["doc_id"], "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            result = self.request("POST", f"/collections/{collection}/points/scroll", json=body).get("result") or {}
            for point in result.get("points") or []:
                payload = point.get("payload") or {}
                doc_id = payload.get("doc_id")
                if isinstance(doc_id, str):
                    doc_ids.add(doc_id)
            offset = result.get("next_page_offset")
            if offset is None:
                break
        return doc_ids

    def upsert_points(self, collection: str, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        self.request("PUT", f"/collections/{collection}/points?wait=true", json={"points": points})


class IonosEmbeddings:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": texts},
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"IONOS embeddings -> {response.status_code}: {response.text[:300]}")
        body = response.json()
        vectors = [item.get("embedding") for item in sorted(body.get("data") or [], key=lambda item: item.get("index", 0))]
        if len(vectors) != len(texts):
            raise RuntimeError(f"expected {len(texts)} embeddings, got {len(vectors)}")
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSION:
                raise RuntimeError(f"unexpected embedding dimension: {len(vector) if isinstance(vector, list) else 0}")
        return vectors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Seite {index}]\n{text}")
    return "\n\n".join(pages)


def read_docx(path: Path) -> str:
    document = Document(str(path))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".csv"}:
        return read_text_file(path)
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".docx":
        return read_docx(path)
    raise ValueError(f"unsupported file type: {suffix}")


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 220) -> list[str]:
    clean = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    while "\n\n\n" in clean:
        clean = clean.replace("\n\n\n", "\n\n")
    chunks: list[str] = []
    index = 0
    while index < len(clean):
        end = min(len(clean), index + max_chars)
        if end < len(clean):
            cut = clean.rfind("\n\n", index, end)
            if cut > index + 500:
                end = cut
        part = clean[index:end].strip()
        if part:
            chunks.append(part)
        if end >= len(clean):
            break
        index = max(end - overlap, index + 1)
    return chunks


def is_supported_file(path: Path, root: Path, extensions: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith(".") or path.name.startswith("~$"):
        return False
    if path.suffix.lower() not in extensions:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def iter_collection_files(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if is_supported_file(path, root, extensions))


class KnowledgebaseSync:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = StateStore(config.state_path)
        self.qdrant = QdrantClient(config.qdrant_url)
        self.embeddings = IonosEmbeddings(config.ionos_base_url, config.ionos_api_key, config.embedding_model)
        self.reconcile_lock = threading.Lock()

    def reconcile_all(self) -> None:
        for collection in self.config.collections:
            self.reconcile_collection(collection)

    def reconcile_collection(self, collection: str) -> None:
        with self.reconcile_lock:
            collection_root = self.config.kb_root / collection
            self.qdrant.ensure_collection(collection)
            state_collection = self.state.collection(collection)
            state_files: dict[str, Any] = state_collection.setdefault("files", {})
            files = iter_collection_files(collection_root, self.config.supported_extensions)
            seen = {path.relative_to(collection_root).as_posix() for path in files}
            seen_doc_ids = {f"{collection}/{rel_path}" for rel_path in seen}

            force = bool(state_files) and self.qdrant.count(collection) == 0
            if force:
                print(f"reindex_forced collection={collection} reason=qdrant_empty_state_present", flush=True)

            for rel_path in sorted(set(state_files) - seen):
                doc_id = f"{collection}/{rel_path}"
                self.qdrant.delete_document(collection, doc_id)
                del state_files[rel_path]
                print(f"deleted collection={collection} file={rel_path}", flush=True)

            for doc_id in sorted(self.qdrant.scroll_doc_ids(collection) - seen_doc_ids):
                if not doc_id.startswith(f"{collection}/"):
                    continue
                self.qdrant.delete_document(collection, doc_id)
                print(f"deleted_orphan collection={collection} doc_id={doc_id}", flush=True)

            for path in files:
                rel_path = path.relative_to(collection_root).as_posix()
                digest = sha256_file(path)
                previous = state_files.get(rel_path) or {}
                if not force and previous.get("sha256") == digest:
                    continue
                self.index_file(collection, collection_root, path, digest)

            state_collection["last_reconcile_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.state.save()

    def index_file(self, collection: str, collection_root: Path, path: Path, digest: str) -> None:
        rel_path = path.relative_to(collection_root).as_posix()
        doc_id = f"{collection}/{rel_path}"
        try:
            text = extract_text(path)
            chunks = chunk_text(text)
        except Exception as exc:
            print(f"extract_failed collection={collection} file={rel_path} error={exc}", flush=True)
            return

        self.qdrant.delete_document(collection, doc_id)
        points: list[dict[str, Any]] = []
        for offset in range(0, len(chunks), 8):
            batch = chunks[offset : offset + 8]
            vectors = self.embeddings.embed(batch)
            for batch_index, vector in enumerate(vectors):
                chunk_index = offset + batch_index
                content = batch[batch_index]
                payload = {
                    "content": content,
                    "text": content,
                    "kb": collection,
                    "doc_id": doc_id,
                    "source_path": rel_path,
                    "chunk_index": chunk_index,
                    "metadata": {
                        "doc_id": doc_id,
                        "kb": collection,
                        "source_path": rel_path,
                        "filename": path.name,
                        "chunk_index": chunk_index,
                        "source": "kb-sync",
                    },
                }
                points.append({"id": stable_uuid(f"{doc_id}#{chunk_index}"), "vector": vector, "payload": payload})

        self.qdrant.upsert_points(collection, points)
        files = self.state.collection(collection).setdefault("files", {})
        files[rel_path] = {
            "sha256": digest,
            "chunks": len(points),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(f"indexed collection={collection} file={rel_path} chunks={len(points)}", flush=True)


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, sync: KnowledgebaseSync) -> None:
        self.sync = sync
        self.timer: threading.Timer | None = None
        self.lock = threading.Lock()

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.sync.config.debounce_seconds, self.sync.reconcile_all)
            self.timer.daemon = True
            self.timer.start()


def main() -> int:
    config = load_config()
    missing_roots = [name for name in config.collections if not (config.kb_root / name).exists()]
    if missing_roots:
        raise RuntimeError(f"knowledgebase directories missing: {', '.join(missing_roots)}")

    sync = KnowledgebaseSync(config)
    sync.reconcile_all()

    stop = threading.Event()
    observer = Observer()
    handler = DebouncedHandler(sync)
    for collection in config.collections:
        observer.schedule(handler, str(config.kb_root / collection), recursive=True)
    observer.start()

    def shutdown(_signum: int, _frame: Any) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(
        "kb_sync_started "
        f"root={config.kb_root} collections={','.join(config.collections)} model={config.embedding_model}",
        flush=True,
    )

    try:
        while not stop.wait(config.reconcile_interval_seconds):
            sync.reconcile_all()
    finally:
        observer.stop()
        observer.join(timeout=10)
        sync.state.save()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"kb_sync_fatal error={exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
