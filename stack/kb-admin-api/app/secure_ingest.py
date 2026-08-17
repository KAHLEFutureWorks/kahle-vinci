from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import socket
import struct
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests
from pypdf import PdfReader, PdfWriter


class IngestError(ValueError):
    """Stable, user-safe rejection reason for the upload interface."""


@dataclass(frozen=True)
class InspectedFile:
    filename: str
    extension: str
    media_type: str
    size: int
    sha256: str
    page_count: int | None = None


@dataclass(frozen=True)
class InjectionFinding:
    risk: str
    signals: tuple[str, ...]


@dataclass(frozen=True)
class IngestResult:
    inspected: InspectedFile
    original_path: Path
    markdown_path: Path
    markdown_sha256: str
    injection: InjectionFinding
    conversion_quality: str = "good"
    conversion_issues: tuple[str, ...] = ()


class MalwareScanner(Protocol):
    def scan(self, filename: str, data: bytes) -> None: ...


class MarkdownConverter(Protocol):
    def convert(self, filename: str, data: bytes, title: str) -> str: ...


class SecureFileInspector:
    OFFICE_ROOTS = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
    MEDIA_TYPES = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain",
        "md": "text/markdown",
    }

    def __init__(self, max_bytes: int = 50 * 1024 * 1024, max_pdf_pages: int = 1000,
                 max_office_pages: int = 200):
        self.max_bytes = max_bytes
        self.max_pdf_pages = max_pdf_pages
        self.max_office_pages = max_office_pages

    def inspect(self, filename: str, data: bytes) -> InspectedFile:
        safe_name = Path(filename or "").name
        if not safe_name or safe_name != filename or safe_name in {".", ".."}:
            raise IngestError("invalid_filename")
        extension = Path(safe_name).suffix.lower().lstrip(".")
        if extension not in self.MEDIA_TYPES:
            raise IngestError("file_type_not_allowed")
        if not data:
            raise IngestError("empty_file")
        if len(data) > self.max_bytes:
            raise IngestError("file_too_large")

        pages = None
        if extension == "pdf":
            if not data.startswith(b"%PDF-"):
                raise IngestError("file_type_mismatch")
            if any(marker in data for marker in (b"/JavaScript", b"/EmbeddedFile", b"/Launch", b"/OpenAction")):
                raise IngestError("embedded_executable_content_not_allowed")
            try:
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    raise IngestError("encrypted_file_not_allowed")
                pages = len(reader.pages)
            except IngestError:
                raise
            except Exception as exc:
                raise IngestError("invalid_pdf") from exc
            if pages > self.max_pdf_pages:
                raise IngestError("pdf_page_limit_exceeded")
        elif extension in self.OFFICE_ROOTS:
            pages = self._inspect_office(extension, data)
            if pages > self.max_office_pages:
                raise IngestError("office_page_limit_exceeded")
        else:
            self._inspect_text(data)

        return InspectedFile(
            filename=safe_name,
            extension=extension,
            media_type=self.MEDIA_TYPES[extension],
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            page_count=pages,
        )

    def sanitize_pdf_for_admin_review(self, filename: str, data: bytes) -> bytes:
        """Create a passive PDF containing visible pages only.

        This is deliberately limited to PDFs. Office macros and embedded Office
        objects cannot be made trustworthy by a generic server-side rewrite.
        The rebuilt PDF drops the original catalog, attachments, JavaScript,
        forms, annotations and automatic actions before it is inspected again.
        """
        safe_name = Path(filename or "").name
        if safe_name != filename or Path(safe_name).suffix.lower() != ".pdf":
            raise IngestError("security_review_not_available")
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise IngestError("encrypted_file_not_allowed")
            writer = PdfWriter()
            for source_page in reader.pages:
                writer.add_page(source_page)
                page = writer.pages[-1]
                # Annotations may contain file attachments, URI/launch actions
                # or JavaScript. A knowledge document does not need them.
                if "/Annots" in page:
                    del page["/Annots"]
                if "/AA" in page:
                    del page["/AA"]
            output = io.BytesIO()
            writer.write(output)
            sanitized = output.getvalue()
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError("security_review_sanitization_failed") from exc
        # The normal gate remains authoritative. Never create an override that
        # can silently carry one of the forbidden structures forward.
        self.inspect(filename, sanitized)
        return sanitized

    def _inspect_office(self, extension: str, data: bytes) -> int:
        if data.startswith(bytes.fromhex("D0CF11E0")):
            raise IngestError("encrypted_or_legacy_office_not_allowed")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = {name.replace("\\", "/").lower() for name in archive.namelist()}
                if "[content_types].xml" not in names:
                    raise IngestError("file_type_mismatch")
                if not any(name.startswith(self.OFFICE_ROOTS[extension]) for name in names):
                    raise IngestError("file_type_mismatch")
                if any(name.endswith("vbaproject.bin") for name in names):
                    raise IngestError("macros_not_allowed")
                executable_extensions = (".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar")
                if any("/embeddings/" in name or name.endswith(executable_extensions) for name in names):
                    raise IngestError("embedded_executable_content_not_allowed")
                content_types = archive.read("[Content_Types].xml").lower()
                if b"macroenabled" in content_types or b"vba" in content_types:
                    raise IngestError("macros_not_allowed")
                if any("encryptedpackage" in name or "encryptioninfo" in name for name in names):
                    raise IngestError("encrypted_file_not_allowed")
                return self._office_page_count(extension, archive, names)
        except IngestError:
            raise
        except (zipfile.BadZipFile, KeyError) as exc:
            raise IngestError("invalid_office_file") from exc

    @staticmethod
    def _office_page_count(extension: str, archive: zipfile.ZipFile, names: set[str]) -> int:
        if extension == "pptx":
            return max(1, sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", name)) for name in names))
        if extension == "docx":
            if "docprops/app.xml" in names:
                app = archive.read(next(name for name in archive.namelist() if name.lower() == "docprops/app.xml"))
                match = re.search(rb"<Pages>(\d+)</Pages>", app, re.I)
                if match:
                    return max(1, int(match.group(1)))
            document_name = next(name for name in archive.namelist() if name.lower() == "word/document.xml")
            document = archive.read(document_name)
            return max(1, len(re.findall(rb"<w:br\b[^>]*w:type=[\"']page[\"']", document)) + 1)
        # Spreadsheet print pages are not reliably stored. Estimate conservatively from
        # used ranges (50 rows x 10 columns per printed page) and explicit page breaks.
        pages = 0
        for name in archive.namelist():
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name.lower()):
                continue
            xml = archive.read(name)
            dimension = re.search(rb"<dimension\b[^>]*ref=[\"'](?:[A-Z]+\d+:)?([A-Z]+)(\d+)[\"']", xml)
            if dimension:
                col_letters, rows = dimension.group(1).decode(), int(dimension.group(2))
                cols = 0
                for letter in col_letters:
                    cols = cols * 26 + ord(letter) - 64
                pages += max(1, math.ceil(rows / 50) * math.ceil(cols / 10))
            else:
                pages += 1
            pages += len(re.findall(rb"<brk\b", xml))
        return max(1, pages)

    @staticmethod
    def _inspect_text(data: bytes) -> None:
        if b"\x00" in data[:8192]:
            raise IngestError("file_type_mismatch")
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                data.decode(encoding)
                return
            except UnicodeDecodeError:
                continue
        raise IngestError("invalid_text_encoding")


class QuarantineStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def store(self, document_id: str, version_id: str, extension: str, data: bytes) -> Path:
        for value in (document_id, version_id):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                raise IngestError("invalid_storage_identifier")
        target_dir = (self.root / document_id / version_id).resolve()
        if self.root not in target_dir.parents:
            raise IngestError("invalid_storage_path")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"original.{extension}"
        if target.exists():
            raise IngestError("original_already_exists")
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def store_markdown(self, original_path: Path, markdown: str) -> Path:
        target = original_path.with_name("rag.md")
        if target.exists():
            raise IngestError("markdown_already_exists")
        target.write_text(markdown, encoding="utf-8", newline="\n")
        return target


class ClamAVScanner:
    """ClamAV INSTREAM adapter. Scanner outages fail closed."""

    def __init__(self, host: str = "clamav", port: int = 3310, timeout: float = 30.0, retries: int = 3):
        self.host, self.port, self.timeout, self.retries = host, port, timeout, max(1, retries)

    def scan(self, filename: str, data: bytes) -> None:
        last_error: OSError | None = None
        response = ""
        for attempt in range(self.retries):
            try:
                with socket.create_connection((self.host, self.port), self.timeout) as connection:
                    connection.settimeout(self.timeout)
                    connection.sendall(b"zINSTREAM\0")
                    for offset in range(0, len(data), 1024 * 1024):
                        chunk = data[offset : offset + 1024 * 1024]
                        connection.sendall(struct.pack(">I", len(chunk)) + chunk)
                    connection.sendall(struct.pack(">I", 0))
                    response = connection.recv(4096).decode("utf-8", errors="replace")
                break
            except OSError as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.25 * (2 ** attempt))
        else:
            raise IngestError("malware_scanner_unavailable") from last_error
        if " FOUND" in response:
            raise IngestError("malware_detected")
        if " OK" not in response:
            raise IngestError("malware_scan_failed")


class DocumentWorkerAdapter:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300.0, retries: int = 3):
        self.base_url, self.api_key, self.timeout, self.retries = base_url.rstrip("/"), api_key, timeout, max(1, retries)

    def convert(self, filename: str, data: bytes, title: str) -> str:
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        last_error: requests.RequestException | None = None
        for attempt in range(self.retries):
            try:
                response = requests.post(
                    f"{self.base_url}/bundle/to_md",
                    headers=headers,
                    files={"files": (filename, data, "application/octet-stream")},
                    data={"title": title, "mode": "raw"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.25 * (2 ** attempt))
        else:
            raise IngestError("document_conversion_failed") from last_error
        markdown = response.content.decode("utf-8", errors="strict").strip()
        if not markdown:
            raise IngestError("document_conversion_empty")
        return markdown + "\n"


class PromptInjectionInspector:
    RULES = {
        "ignore_instructions": re.compile(r"\b(ignore|disregard|forget)\b.{0,50}\b(instruction|prompt|system)\b", re.I | re.S),
        "system_prompt_request": re.compile(r"\b(system prompt|developer message|hidden instructions?)\b", re.I),
        "tool_or_secret_request": re.compile(r"\b(call|use|execute|reveal|show)\b.{0,60}\b(tool|password|secret|token|api key)\b", re.I | re.S),
        "role_override": re.compile(r"\b(you are now|act as|new role|jailbreak)\b", re.I),
    }

    def inspect(self, markdown: str) -> InjectionFinding:
        signals = tuple(name for name, rule in self.RULES.items() if rule.search(markdown))
        risk = "high" if len(signals) >= 2 else "medium" if signals else "none"
        return InjectionFinding(risk=risk, signals=signals)


class ConversionQualityInspector:
    MOJIBAKE = ("\u00c3", "\u00c2", "\u00e2\u20ac", "\ufffd")

    def inspect(self, markdown: str) -> tuple[str, tuple[str, ...]]:
        issues: list[str] = []
        if len((markdown or "").strip()) < 20:
            issues.append("conversion_output_too_short")
        if any(marker in (markdown or "") for marker in self.MOJIBAKE):
            issues.append("character_encoding_corrupted")
        table_rows = [(number, line) for number, line in enumerate((markdown or "").splitlines(), 1)
                      if line.strip().startswith("|")]
        if table_rows:
            content_rows = [(number, line.count("|")) for number, line in table_rows
                            if not re.fullmatch(r"[| :\-]+", line.strip())]
            if content_rows:
                expected = max(set(width for _, width in content_rows),
                               key=lambda width: sum(item_width == width for _, item_width in content_rows))
                for number, width in content_rows:
                    if width != expected:
                        issues.append(
                            f"table_column_structure_inconsistent:line={number}:expected={expected - 1}:actual={width - 1}"
                        )
        blocking = {"character_encoding_corrupted", "conversion_output_too_short"}
        return ("failed" if blocking.intersection(issues)
                else "low" if issues else "good", tuple(issues))


class SecureIngestPipeline:
    def __init__(self, inspector: SecureFileInspector, scanner: MalwareScanner, converter: MarkdownConverter,
                 storage: QuarantineStorage, injection_inspector: PromptInjectionInspector | None = None):
        self.inspector = inspector
        self.scanner = scanner
        self.converter = converter
        self.storage = storage
        self.injection_inspector = injection_inspector or PromptInjectionInspector()
        self.quality_inspector = ConversionQualityInspector()

    def ingest(self, document_id: str, version_id: str, filename: str, data: bytes, title: str) -> IngestResult:
        inspected = self.inspector.inspect(filename, data)
        self.scanner.scan(filename, data)
        original = self.storage.store(document_id, version_id, inspected.extension, data)
        try:
            markdown = self.converter.convert(filename, data, title)
            injection = self.injection_inspector.inspect(markdown)
            conversion_quality, conversion_issues = self.quality_inspector.inspect(markdown)
            markdown_path = self.storage.store_markdown(original, markdown)
        except Exception:
            # Original remains quarantined for audit/diagnosis; it is never published implicitly.
            raise
        return IngestResult(
            inspected=inspected,
            original_path=original,
            markdown_path=markdown_path,
            markdown_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            injection=injection, conversion_quality=conversion_quality,
            conversion_issues=conversion_issues,
        )


class ScreenshotInspector:
    """
    Pruefung fuer Bildanhaenge an Wissensfehlermeldungen.

    Bewusst getrennt von SecureFileInspector: Dort gelten Dokumentformate und
    Seitengrenzen, hier zaehlt nur, dass wirklich ein Bild ankommt. Der Typ wird
    ausschliesslich am Dateiinhalt bestimmt; die Endung ist nicht
    vertrauenswuerdig. SVG ist nicht zugelassen, weil es Skripte tragen kann.
    """

    SIGNATURES = (
        (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
        (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    )
    # Marker, die in einem echten Rasterbild nichts zu suchen haben.
    ACTIVE_CONTENT = (b"<script", b"<?php", b"<svg", b"javascript:")

    def __init__(self, max_bytes: int = 5 * 1024 * 1024):
        self.max_bytes = max_bytes

    def inspect(self, data: bytes) -> tuple[str, str]:
        """Gibt Endung und Medientyp zurueck oder wirft IngestError."""
        if not data:
            raise IngestError("empty_file")
        if len(data) > self.max_bytes:
            raise IngestError("screenshot_too_large")
        for signature, extension, media_type in self.SIGNATURES:
            if data.startswith(signature):
                break
        else:
            raise IngestError("screenshot_type_not_allowed")
        head = data[:4096].lower()
        if any(marker in head for marker in self.ACTIVE_CONTENT):
            raise IngestError("embedded_executable_content_not_allowed")
        return extension, media_type
