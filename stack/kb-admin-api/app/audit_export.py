from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


@dataclass(frozen=True)
class AuditEntry:
    occurred_at: str
    actor_user_id: str
    event_type: str
    subject_type: str
    subject_id: str
    details: str


class AuditExporter:
    def __init__(self, store: SQLiteGovernanceStore):
        self.store = store

    def entries(self, limit: int = 10_000) -> list[AuditEntry]:
        limit = max(1, min(limit, 50_000))
        with self.store.connect() as db:
            governance = db.execute(
                "SELECT occurred_at, actor_user_id, event_type, subject_type, subject_id, details_json "
                "FROM governance_audit ORDER BY occurred_at DESC, sequence DESC LIMIT ?", (limit,),
            ).fetchall()
            lifecycle = db.execute(
                "SELECT created_at occurred_at, actor_user_id, event_type, 'document_case' subject_type, "
                "case_id subject_id, details_json FROM document_events "
                "ORDER BY created_at DESC, sequence DESC LIMIT ?", (limit,),
            ).fetchall()
        rows = [AuditEntry(*tuple(row)) for row in (*governance, *lifecycle)]
        return sorted(rows, key=lambda row: row.occurred_at, reverse=True)[:limit]

    def csv_bytes(self, limit: int = 10_000) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(("Zeitpunkt", "Akteur", "Ereignis", "Objekttyp", "Objekt-ID", "Details"))
        for row in self.entries(limit):
            writer.writerow((row.occurred_at, row.actor_user_id, row.event_type,
                             row.subject_type, row.subject_id, row.details))
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def pdf_bytes(self, limit: int = 2_000) -> bytes:
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
        width, height = A4
        y = height - 40
        pdf.setTitle("KAHLE-Vinci Auditexport")
        pdf.setFont("Helvetica-Bold", 14); pdf.drawString(36, y, "KAHLE-Vinci Auditexport"); y -= 24
        pdf.setFont("Helvetica", 7)
        for row in self.entries(limit):
            text = f"{row.occurred_at} | {row.actor_user_id} | {row.event_type} | {row.subject_type}:{row.subject_id}"
            if y < 35:
                pdf.showPage(); pdf.setFont("Helvetica", 7); y = height - 35
            pdf.drawString(36, y, text[:145]); y -= 10
        pdf.save()
        return output.getvalue()
