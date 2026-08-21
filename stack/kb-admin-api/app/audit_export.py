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
    actor_name: str
    event_label: str
    subject_label: str
    details_label: str


EVENT_LABELS = {
    "identity_synced": "Benutzerkonto mit der Anmeldung abgeglichen",
    "role_changed": "Benutzerrolle geändert",
    "user_activation_changed": "Benutzerzugang geändert",
    "knowledgebase_access_changed": "Zugriffsrechte auf Wissensbereich geändert",
    "knowledgebase_change_requested": "Änderung eines Wissensbereichs beantragt",
    "knowledgebase_change_decided": "Änderung eines Wissensbereichs entschieden",
    "knowledgebase_created": "Wissensbereich erstellt",
    "knowledgebase_renamed": "Wissensbereich umbenannt",
    "knowledgebase_archived": "Wissensbereich archiviert",
    "knowledgebase_deleted": "Wissensbereich gelöscht",
    "submitted": "Dokument hochgeladen",
    "markdown_revised": "Dokumentinhalt aktualisiert",
    "confidentiality_changed": "Dokumenteinstufung geändert",
    "authority_updated": "Dokumentart und Verbindlichkeit geändert",
    "authority_relation_created": "Beziehung zwischen Dokumenten angelegt",
    "activated": "Dokument veröffentlicht",
    "activation_rolled_back": "Dokumentveröffentlichung zurückgesetzt",
    "superseded_version_purged": "Abgelöste Dokumentversion endgültig bereinigt",
    "archived_version_restored": "Frühere Dokumentversion wiederhergestellt",
    "archived_version_restore_rolled_back": "Wiederherstellung einer früheren Dokumentversion zurückgesetzt",
    "moved_to_trash": "Dokument in den Papierkorb verschoben",
    "restored_from_trash": "Dokument aus dem Papierkorb wiederhergestellt",
    "document_deleted_from_trash": "Dokument endgültig gelöscht",
    "target_knowledgebase_changed": "Ziel-Wissensbereich geändert",
    "target_knowledgebases_changed": "Ziel-Wissensbereiche geändert",
    "document_publication_changed": "Dokumentzuordnung geändert",
    "publication_changed": "Dokumentzuordnung geändert",
    "document_change_approved": "Dokumentänderung freigegeben",
    "feedback_screenshot_attached": "Screenshot an Wissensfehlermeldung angehängt",
    "quality_case_message_sent": "Rückmeldung zu einem Qualitätsfall gesendet",
    "quality_case_resolved": "Qualitätsfall abgeschlossen",
    "portal_setting_changed": "Portaleinstellung geändert",
    "owner_proposal_permission_changed": "Berechtigung zur Owner-Auswahl geändert",
    "owner_reassignment_confirmed": "Owner-Wechsel bestätigt",
    "owner_reassignment_rejected": "Owner-Wechsel abgelehnt",
    "manager_assigned": "Führungskraft zugeordnet",
    "delegate_assigned": "Vertretung eingerichtet",
    "delegate_removed": "Vertretung entfernt",
    "manager_absence_set": "Abwesenheit eingetragen",
    "manager_absence_removed": "Abwesenheit entfernt",
    "outlook_absence_synced": "Abwesenheit aus Outlook übernommen",
    "outlook_absence_removed": "Outlook-Abwesenheit beendet",
    "initial_owner_proposed": "Anderer Dokument-Owner vorgeschlagen",
    "analysis_recorded": "Automatische Dokumentanalyse abgeschlossen",
}

DETAIL_LABELS = {
    "email": "E-Mail", "active": "Zugang aktiv", "role": "Rolle",
    "target_user_id": "Betroffener Benutzer", "can_read": "Lesen erlaubt",
    "can_upload": "Upload erlaubt", "allowed": "Erlaubt", "reason": "Begründung",
    "resolution": "Abschlussnotiz", "knowledgebase_id": "Wissensbereich",
    "knowledgebase_ids": "Wissensbereiche", "owner_user_id": "Dokument-Owner",
    "before_label": "Vorheriger Name", "after_label": "Neuer Name",
    "before_status": "Vorheriger Status", "after_status": "Neuer Status",
    "change_type": "Änderungsart", "slug": "Kurzname", "purpose": "Zweck",
    "source": "Quelle", "absent_from": "Abwesend von", "absent_until": "Abwesend bis",
    "proposed_owner_user_id": "Vorgeschlagener Owner",
    "contradiction_document_ids": "Dokumente mit Widersprüchen",
    "conversion_quality": "Qualität der Aufbereitung", "cross_kb_matches": "Treffer in anderen Wissensbereichen",
    "exact_duplicate_document_id": "Identisches Dokument", "malware_safe": "Schadsoftwareprüfung bestanden",
    "normalized_duplicate_document_id": "Inhaltsgleiches Dokument", "notes": "Hinweise",
    "prompt_injection_risk": "Risiko manipulativer Anweisungen", "restricted_terms": "Gefundene Sperrwörter",
    "same_kb_similarity": "Ähnlichkeit im Wissensbereich", "status": "Verarbeitungsstatus",
    "version_candidate_document_ids": "Mögliche Vorgängerversionen",
    "previous_version_id": "Vorherige aktive Version", "restored_version_id": "Wiederhergestellte Version",
}


# Diese Kennungen werden von Hintergrundprozessen geschrieben und sind keine
# Benutzerkonten. Sie müssen im Audit verständlich erscheinen, ohne einen
# tatsächlich nicht auflösbaren Nutzer zu kaschieren.
TECHNICAL_ACTOR_LABELS = {
    "system": "System",
    "migration": "System: Bestandsübernahme",
    "classifier": "System: automatische Klassifizierung",
    "indexer": "System: Veröffentlichung und Indexierung",
    "auto_activation": "System: automatische Veröffentlichung",
}


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
            user_names = {row["user_id"]: row["display_name"] for row in db.execute(
                "SELECT user_id,display_name FROM portal_users"
            )}
            base_names = {row["knowledgebase_id"]: row["label"] for row in db.execute(
                "SELECT knowledgebase_id,label FROM knowledgebases"
            )}
            document_names = {row["document_id"]: row["title"] for row in db.execute(
                "SELECT document_id,title FROM canonical_documents"
            )}
            case_names = {row["case_id"]: row["title"] for row in db.execute(
                "SELECT c.case_id,d.title FROM document_cases c "
                "JOIN canonical_documents d ON d.document_id=c.document_id"
            )}
        rows = []
        for raw in (*governance, *lifecycle):
            occurred_at, actor_id, event_type, subject_type, subject_id, details = tuple(raw)
            subject_label = {
                "user": user_names.get(subject_id, "Benutzerkonto"),
                "knowledgebase": base_names.get(subject_id, "Wissensbereich"),
                "document": document_names.get(subject_id, "Dokument"),
                "document_case": case_names.get(subject_id, "Dokumentvorgang"),
                "rag_feedback": "Wissensfehlermeldung",
                "feedback": "Wissensfehlermeldung",
                "incident": "Technischer Qualitätsfall",
            }.get(subject_type, subject_type.replace("_", " ").capitalize())
            rows.append(AuditEntry(
                occurred_at, actor_id, event_type, subject_type, subject_id, details,
                user_names.get(
                    actor_id,
                    TECHNICAL_ACTOR_LABELS.get(actor_id, "Unbekannter Benutzer"),
                ),
                EVENT_LABELS.get(event_type, event_type.replace("_", " ").capitalize()),
                subject_label, self._friendly_details(details, user_names, base_names, document_names),
            ))
        return sorted(rows, key=lambda row: row.occurred_at, reverse=True)[:limit]

    @staticmethod
    def _friendly_details(raw: str, user_names: dict[str, str], base_names: dict[str, str], document_names: dict[str, str]) -> str:
        try:
            details = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return "Keine weiteren Angaben"
        if not details:
            return "Keine weiteren Angaben"
        values = []
        for key, value in details.items():
            label = DETAIL_LABELS.get(key, key.replace("_", " ").capitalize())
            if key.endswith("user_id"):
                value = user_names.get(str(value), "Unbekannter Benutzer")
            elif key.endswith("document_ids") and isinstance(value, list):
                value = ", ".join(document_names.get(str(item), str(item)) for item in value) or "Keine"
            elif key.endswith("document_id") and value:
                value = document_names.get(str(value), str(value))
            elif key == "knowledgebase_ids" and isinstance(value, list):
                value = ", ".join(
                    base_names.get(str(item), "Unbekannter Wissensbereich") for item in value
                )
            elif key.endswith("knowledgebase_id"):
                value = base_names.get(str(value), "Unbekannter Wissensbereich")
            elif isinstance(value, bool):
                value = "Ja" if value else "Nein"
            elif isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            translations = {
                "good": "Gut", "none": "Keine",
                "create": "Als eigenständiges Dokument vorschlagen",
                "replace": "Als neue Version veröffentlichen",
                "publish_existing": "Vorhandenes Dokument zusätzlich veröffentlichen",
                "discard": "Upload verwerfen",
                "withdrawn": "Verworfen", "rejected": "Abgelehnt",
                "pending_employee_decision": "Entscheidung des Uploaders offen",
                "pending_manager_approval": "Prüfung durch Führungskraft",
                "pending_admin_approval": "Prüfung durch Admin",
                "ready_to_activate": "Bereit zur Veröffentlichung",
                "active": "Veröffentlicht",
                "needs_correction": "Korrektur erforderlich",
                "security_blocked": "Sicherheitsprüfung erforderlich",
                "duplicate_blocked": "Identisches Dokument gefunden",
            }
            if isinstance(value, str):
                value = value.replace("Owner f?r Erstver?ffentlichung vorgeschlagen", "Owner für Erstveröffentlichung vorgeschlagen")
                value = translations.get(value, value)
            values.append(f"{label}: {value}")
        return "; ".join(values)

    def csv_bytes(self, limit: int = 10_000) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(("Zeitpunkt", "Ausgeführt von", "Aktion", "Betroffenes Element", "Beschreibung", "Technische Referenz"))
        for row in self.entries(limit):
            writer.writerow((row.occurred_at, row.actor_name, row.event_label,
                             row.subject_label, row.details_label, row.subject_id))
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
            text = f"{row.occurred_at} | {row.actor_name} | {row.event_label} | {row.subject_label}"
            if y < 35:
                pdf.showPage(); pdf.setFont("Helvetica", 7); y = height - 35
            pdf.drawString(36, y, text[:145]); y -= 10
            if row.details_label != "Keine weiteren Angaben":
                pdf.drawString(48, y, row.details_label[:140]); y -= 10
        pdf.save()
        return output.getvalue()
