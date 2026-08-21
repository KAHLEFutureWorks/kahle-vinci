import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, root), "utf8");

test("renders the role-based KAHLE-Vinci knowledge portal", async () => {
  const [page, portal, styles, headerStyles, layout, favicon, dockerfile] = await Promise.all([
    source("app/page.tsx"), source("components/KnowledgePortal.tsx"),
    source("app/portal.css"), source("app/header-actions.css"), source("app/layout.tsx"),
    source("public/favicon.svg"), source("Dockerfile"),
  ]);
  assert.match(page, /<KnowledgePortal \/>/);
  assert.match(portal, /Dokument bereitstellen/);
  assert.match(portal, /Datei hier ablegen/);
  assert.match(portal, /Dokument-Owner/);
  assert.match(portal, /portal\/upload-jobs/);
  assert.match(portal, /Abwesenheiten/);
  assert.match(portal, /Andere Dokument-Owner vorschlagen/);
  assert.match(portal, /Meine Vorgänge/);
  assert.match(portal, /Admin-Aufgaben/);
  assert.match(portal, /Benutzer & Rechte/);
  assert.doesNotMatch(portal, /portal\/auth\/step-up\/start/);
  assert.match(portal, /credentials: "include"/);
  assert.match(portal, /\/wissen\/api/);
  assert.match(portal, /<Link className="wp-back-link" href="\/" aria-label="Zurück zu KAHLE-Vinci"/);
  assert.match(portal, /<ArrowLeft size=\{17\} \/>/);
  assert.match(headerStyles, /\.wp-back-link\s*\{/);
  assert.match(layout, /icon: "\/wissen\/favicon\.svg"/);
  assert.match(layout, /title: "KAHLE-Vinci Wissensportal"/);
  assert.match(favicon, /fill="#168dd4"/);
  assert.doesNotMatch(portal, /Qualit\?|Pr\?fung|F\?hr|G\?lt|L\?sch|\?nder|\?ber|\?ff/);
  assert.match(styles, /\.wp-shell/);
  assert.match(styles, /@media/);
  assert.match(dockerfile, /DASHBOARD_BASE_PATH=\/wissen/);
});

test("meets the PRD accessibility and plain-language requirements", async () => {
  const [portal, styles, headerStyles, uploadStyles] = await Promise.all([
    source("components/KnowledgePortal.tsx"), source("app/portal.css"),
    source("app/header-actions.css"), source("app/upload-result.css"),
  ]);

  // PRD 26.3: erkennbare Fokuszustände und Tastaturbedienung.
  assert.match(styles, /:focus-visible\{[^}]*outline:/);
  // Auswahlflächen sind echte Buttons und damit ohne Zutun tastaturbedienbar.
  assert.doesNotMatch(portal, /<article[^>]*onClick=/);
  assert.match(portal, /<button\s+type="button"\s+className="wp-doc-head"[\s\S]*?aria-expanded=/);
  // Die Benutzerauswahl ist ein echter Button statt eines klickbaren <article>.
  assert.match(portal, /<aside className="wp-user-directory" aria-label="Benutzer auswählen">/);
  assert.doesNotMatch(portal, /<article[^>]*className=\{selected === user\.user_id[^>]*onClick=/);

  // PRD 21.1: keine technischen Fehlercodes in der Oberfläche.
  assert.doesNotMatch(portal, /set(Error|Message)\(cause instanceof Error \? cause\.message/);
  assert.match(portal, /friendlyError\(cause,/);

  // PRD 16.1: dreistufige Bewertung der Aufbereitung.
  for (const level of ["Alles in Ordnung", "Bitte prüfen", "Upload kann so nicht verarbeitet werden"]) {
    assert.ok(portal.includes(level), `Bewertungsstufe fehlt: ${level}`);
  }

  // PRD 12.3: fünf verständliche Stufen, Verarbeitung läuft ohne offene Seite weiter.
  for (const step of ["uploaded", "security", "conversion", "comparison", "completed"]) {
    assert.match(portal, new RegExp(`${step}: "`));
  }
  assert.match(portal, /die Prüfung läuft weiter/);
  assert.match(portal, /sessionStorage\.getItem\(RUNNING_UPLOAD_JOB\)/);

  // Formularfelder brauchen einen sichtbaren Rahmen, sonst sind sie weiß auf weiß.
  assert.match(styles, /:where\(\.wp-shell input[^)]*\)[^{]*\{[^}]*border:/);
  // Beschriftung über dem Feld, sonst überlappt der Fokusrahmen den Text.
  assert.match(styles, /\.wp-form>label\{[^}]*flex-direction:column/);

  // Der Dateiname belegt den Titel vor, statt ihn abtippen zu lassen.
  assert.match(portal, /function titleFromFilename/);
  assert.match(portal, /if \(next && !title\.trim\(\)\) setTitle\(titleFromFilename/);
  // Entscheider sehen, warum ein Vorgang bei ihnen liegt.
  assert.match(portal, /reviewReason\[task\.status\]/);
  // Auditeinträge zeigen Klarnamen statt roher Benutzer-IDs.
  assert.match(portal, /ausgeführt von \{entry\.actor_name\}/);
  // Kein rohes JSON im Qualitätsdashboard.
  assert.doesNotMatch(portal, /<pre>\{JSON\.stringify/);
  // Dokumentkacheln lassen sich wieder schließen.
  assert.match(portal, /current === documentId \? "" : documentId/);

  // Adminübersicht: Wissensbereiche mit ihren Dokumenten, aufklappbar.
  assert.match(portal, /portal\/admin\/knowledgebase-overview/);
  assert.match(portal, /className="wp-kb-head"[\s\S]*?aria-expanded=/);
  assert.match(styles, /\.wp-kb-overview\{/);

  // Screenshot zur Wissensfehlermeldung, nur Bildformate.
  assert.match(portal, /accept="image\/png,image\/jpeg,\.pdf,\.docx,\.xlsx,\.pptx,\.txt,\.md"/);
  assert.match(portal, /accept="\.pdf,\.docx,\.xlsx,\.pptx,\.txt,\.md"/);
  assert.doesNotMatch(portal, /\.md,\.csv/);
  assert.match(portal, /Dieses Dateiformat wird nicht/);
  assert.match(portal, /feedback\/\$\{result\.feedback_id\}\/screenshot/);

  // Aktionen am Dokument melden Erfolg wie Fehler, statt still abzubrechen.
  assert.match(portal, /Bitte gib zuerst eine Begründung/);
  assert.doesNotMatch(portal, /if\(!selected\|\|reason\.trim\(\)\.length<3\)return/);
  // Trefferstufen als Klartext statt roher Codes, mit Prozentwert.
  assert.match(portal, /matchLevelText\[match\.level\]/);
  assert.match(portal, /match_percent/);

  // Eigene Vorgänge lassen sich aus der Aufgabenliste heraus weiterschicken.
  assert.match(portal, /chooseAction\(task\.case_id, ?"create"\)/);
  assert.match(portal, /chooseAction\(task\.case_id, ?"discard"\)/);
  // Endgültiges Löschen erscheint für Admins erst nach der Schutzfrist und ist zweistufig.
  assert.match(portal, /portal\/admin\/trash\/\$\{id\}\/delete/);
  assert.match(portal, /Dokument endgültig löschen\?/);
  assert.match(portal, /canAdministerTrash\s*&&\s*item\.can_delete/);
  assert.match(portal, /item\.delete_eligible_on/);

  // Endgültiges Entfernen setzt ein Archiv voraus und braucht archivierte Bereiche zur Auswahl.
  assert.match(portal, /knowledgebase_must_be_archived_first/);
  assert.match(portal, /kind === "delete"/);
  assert.match(portal, /base\.status === "archived"/);
  // Anträge nutzen die Breite und nennen Aktion, Bereich und Person im Klartext.
  assert.match(portal, /changeKindText\[change\.kind\]/);
  assert.match(portal, /userNames\[change\.requested_by\]/);

  // Archivieren und Entfernen warnen, wenn Dokumente betroffen sind.
  assert.match(portal, /function affectedDocuments/);
  assert.match(portal, /zugeordnete Dokumente/);
  // Kritische Aktionen nutzen ein einheitliches, verständliches Bestätigungsfenster.
  assert.match(portal, /wp-confirm-dialog/);
  assert.match(portal, /Möchtest du diese Aktion wirklich durchführen/);
  assert.match(portal, /confirmed: true/);
  assert.match(portal, /JSON\.stringify\(\{ approve, reason, confirmed: true \}\)/);
  // Freigaben nennen den Ansprechpartner und erlauben Rückfragen an alle Beteiligten.
  assert.match(portal, /Ansprechpartner: \{task\.contact_name\}/);
  assert.match(portal, /Rückfrage stellen/);
  assert.match(portal, /inquiry-participants/);
  assert.match(portal, /recipient_user_id: inquiryRecipient/);
  assert.match(portal, /Die Rückfrage wurde als Mitteilung und per E-Mail versendet/);
  assert.match(portal, /Ziel-Wissensbereiche/);
  assert.match(portal, /target_knowledgebase_labels/);
  assert.match(portal, /target-knowledgebases/);
  assert.match(portal, /knowledgebase_ids: knowledgebaseIds/);
  assert.match(portal, /selectedKnowledgebaseIds, setSelectedKnowledgebaseIds/);
  assert.match(portal, /type="checkbox"/);
  assert.match(portal, /knowledgebase_ids_json/);
  assert.match(portal, /targetSaveLocks\.current\.has\(caseId\)/);
  assert.match(portal, /targetBusy\[task\.case_id\]/);
  assert.match(portal, /<LoaderCircle className="spin" size=\{16\} \/>/);
  assert.match(portal, /<details className="wp-kb-multiselect/);
  assert.match(headerStyles, /\.wp-kb-options\s*\{[^}]*position:\s*absolute/);
  assert.match(headerStyles, /\.wp-kb-options\s*\{[^}]*max-height:\s*220px/);
  assert.match(headerStyles, /\.wp-kb-options\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(uploadStyles, /\.wp-document-group article\.selected\s*\{[^}]*overflow:\s*visible/);
  assert.match(uploadStyles, /\.wp-document-group article\.selected\s*\{[^}]*z-index:\s*\d+/);
  assert.match(portal, /Vom Nutzer ausgewählt/);
  assert.match(portal, /target_knowledgebase_history/);
  assert.match(portal, /Verlauf des Ziel-Wissensbereichs/);
  const uploadForm = portal.slice(portal.indexOf("function Upload("), portal.indexOf("function Tasks("));
  assert.doesNotMatch(uploadForm, /Wer darf das Dokument sehen\?/);
  assert.match(portal, /form\.append\("confidentiality", "internal"\)/);
  assert.match(uploadForm, /data-visibility-policy="knowledgebase-rights"/);
  assert.match(portal, /Verknüpfte Knowledge Bases/);
  assert.match(portal, /review\.knowledgebases\.map\(\(base\) => base\.label\)/);
  // PRD 9.3: Admins ordnen bestehende Dokumente einem Bereich zu oder lösen die Zuordnung.
  assert.match(portal, /admin\/documents\/\$\{documentId\}\/publications/);
  assert.match(portal, /Verknüpfte Knowledge Bases bearbeiten/);
  assert.match(portal, /publicationSaveLocks\.current\.has\(documentId\)/);
  assert.match(portal, /publicationBusy\[doc\.document_id\]/);
  assert.match(portal, /Mindestens ein Wissensbereich muss mit dem Dokument verknüpft bleiben/);

  // Altbestände werden sichtbar inventarisiert und erst über den normalen Freigabeprozess übernommen.
  assert.match(portal, /Altbestände migrieren/);
  assert.match(portal, /portal\/admin\/migration\/inventory/);
  assert.match(portal, /In regulären Freigabeprozess übernehmen/);
  // Die Migrationsmaske bleibt verständlich: keine JSON-Eingabe und keine
  // frei einzutragenden technischen Autoritätscodes.
  assert.doesNotMatch(portal, /Geltungsbereich als JSON/);
  assert.doesNotMatch(portal, /Autoritätstyp<input/);
  assert.match(portal, /Gesetz oder regulatorische Vorgabe/);
  assert.match(portal, /Wo und für wen gilt das Dokument/);
  assert.match(portal, /Noch zu bearbeiten/);
  assert.match(portal, /Ziel-Wissensbereich/);
  assert.match(portal, /noch keinem Wissensbereich zugeordnet/);
  assert.match(portal, /knowledgebase_id:\s*targetKb\.knowledgebase_id/);
  assert.match(portal, /portal\/admin\/migration\/file\?path=/);
  assert.match(portal, /Original ansehen \(nur Vorschau\)/);
  assert.match(portal, /Markdown ansehen \(nur Vorschau\)/);

  // PRD 27: Workflow-, Sicherheits- und Retrievalkennzahlen sind sichtbar.
  for (const metric of ["Offene Freigaben", "Bearbeitungszeit", "Dubletten", "Widersprüche",
    "Fehlgeschlagene Konvertierungen", "Dokumenttreffer", "Quellenabdeckung",
    "Unbeantwortete interne Fragen", "Retrieval-Latenz", "Retrieval-Fehlerrate"]) {
    assert.ok(portal.includes(metric), `Dashboardkennzahl fehlt: ${metric}`);
  }
  assert.match(portal, /nicht zur individuellen Leistungs- oder Verhaltensbewertung/);

  // Eigene Uploads und fremde Freigaben stehen getrennt.
  assert.match(portal, /Deine Uploads · Entscheidung offen/);
  assert.match(portal, /Zur Freigabe durch dich/);
  assert.match(portal, /Danach geht der Vorgang zur Freigabe/);
  // Freigabeknöpfe erscheinen nie am eigenen Vorgang.
  assert.match(portal, /!own && canDecide && hasReviewDecision/);
  assert.match(portal, /task\.status\.includes\("approval"\) \|\| task\.status === "needs_correction"/);

  // PRD 26.2: keine Fachbegriffe für normale Nutzer.
  assert.match(portal, /confidentialityText\[result\.confidentiality\]/);
  assert.match(portal, /isAdmin \? "RAG-Markdown bearbeiten" : "Aufbereitete Fassung"/);
});

test("edits a selected legacy document inside its expanded card", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  const expandedCard = portal.match(
    /selected\s*===\s*item\.path\s*&&\s*\([\s\S]*?<div className="wp-doc-panel">([\s\S]*?)\{item\.status === "metadata_required" && metadataForm\}/,
  );
  assert.ok(expandedCard, "aufgeklappte Migrationskarte fehlt");
  assert.match(portal, /item\.status === "metadata_required" && metadataForm/);
  const editor = portal.match(/const metadataForm\s*=([\s\S]*?):\s*null;/);
  assert.ok(editor, "Migrationsformular fehlt");
  for (const field of ["Ziel-Wissensbereich", "Verantwortlicher Owner", "Wer darf das Dokument sehen?",
    "Verbindlichkeit", "Wo und für wen gilt das Dokument?"]) {
    assert.ok(editor[1].includes(field), `${field} fehlt im Formular der ausgewählten Dokumentkarte`);
  }
  assert.match(portal, /Dokument auswählen und Angaben bearbeiten/);
  for (const label of ["Unternehmensweit intern", "Nur freigegebene Bereiche", "Nur ausdrücklich berechtigte Personen"]) {
    assert.ok(portal.includes(label), `verständliche Zugriffsstufe fehlt: ${label}`);
  }
  assert.match(portal, /value="excluded">Nicht übernehmen/);
  assert.match(portal, /\/portal\/admin\/migration\/\$\{restore\s*\?\s*"restore"\s*:\s*"exclude"\}/);
  assert.match(portal, /In ‚Nicht übernehmen‘ verschieben/);
  assert.ok(
    portal.indexOf('className="wp-disposition"') <
      portal.indexOf('{item.status === "metadata_required" && metadataForm}'),
    "Die Sofortaktion ‚Nicht übernehmen‘ muss vor dem Metadatenformular stehen",
  );
  assert.match(portal, /Wieder zur Prüfung zurückholen/);
  assert.match(portal, /Kurze Begründung/);
  assert.match(portal, /users\s*\.filter\([\s\S]*?user\.active\s*&&\s*user\.manager_user_id/);
  assert.ok(portal.includes("Für die zweistufige Freigabe werden nur Benutzer mit zugeordneter"));
  assert.ok(portal.includes("Führungskraft angezeigt."));
});

test("keeps server credentials and direct vector access out of the portal bundle", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.doesNotMatch(portal, /IONOS_API_KEY|QDRANT_API_KEY|QDRANT_URL/);
  assert.doesNotMatch(portal, /localStorage/);
  assert.doesNotMatch(portal, /\/collections\//);
});

test("lets admins manage restricted terms and shows matched terms on review tasks", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /Sperrwörter verwalten/);
  assert.match(portal, /\/portal\/admin\/restricted-terms/);
  assert.match(portal, /Gesperrter Begriff gefunden/);
  assert.match(portal, /task\.restricted_terms\.join/);
  assert.match(portal, /Schritt 1 von 2/);
  assert.match(portal, /Dokument wurde noch nicht veröffentlicht/);
  assert.match(portal, /Was passiert jetzt\?/);
  assert.match(portal, /Gefundene gesperrte Begriffe/);
  assert.match(portal, /wp-upload-outcome/);
  assert.match(portal, /Groß- und Kleinschreibung spielt keine Rolle/);
});

test("shows named read notifications and groups searchable documents by knowledgebase", async () => {
  const [portal, resultStyles] = await Promise.all([
    source("components/KnowledgePortal.tsx"),
    source("app/upload-result.css"),
  ]);
  assert.match(portal, /item\.document_title/);
  assert.match(portal, /\/portal\/notifications\/\$\{notificationId\}\/read/);
  assert.doesNotMatch(portal, /nextTab !== "notifications"[\s\S]*?\/portal\/notifications\/read/);
  assert.match(portal, /className=\{`wp-notification-card/);
  assert.match(portal, /notifications\.filter\(\(item\) => !item\.read_at\)/);
  assert.match(portal, /Dokumente suchen/);
  assert.match(portal, /Knowledgebase filtern/);
  assert.match(portal, /Alle Knowledgebases/);
  assert.match(portal, /document\.primary_knowledgebase\?\.knowledgebase_id === knowledgebaseFilter/);
  assert.match(resultStyles, /\.wp-document-filters/);
  assert.match(portal, /primary_knowledgebase/);
  assert.match(portal, /additional_knowledgebases/);
  assert.match(portal, /Zusätzlich verknüpft/);
  assert.match(portal, /const searchable = document\.title\.toLocaleLowerCase/);
  assert.match(portal, /className="wp-notification-title"/);
  assert.match(portal, /params\.get\("document"\).*return "documents"/s);
  assert.match(portal, /focusedDocumentId=\{focusedDocumentId\}/);
  assert.match(portal, /id=\{`portal-document-\$\{doc\.document_id\}`\}/);
  assert.match(portal, />Antworten</);
  assert.match(portal, /\/portal\/notifications\/\$\{item\.notification_id\}\/reply/);
  assert.match(portal, /Chatverlauf anzeigen/);
  assert.match(portal, /\/portal\/notifications\/\$\{item\.notification_id\}\/thread/);
  assert.match(resultStyles, /\.wp-notification-title[^}]*font-weight:\s*800/);
  assert.match(resultStyles, /\.wp-notification-card\.unread[^}]*border:\s*2px solid var\(--blue\)/);
});

test("shows document confidentiality controls only to admins", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /isAdmin && \(\s*<label>\s*Wer darf das Dokument sehen\?/);
  assert.match(portal, /isAdmin && \(\s*<button onClick=\{\(\) => void classification\(\)\}>/);
});

test("accepts approvals immediately and shows background publication separately", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /const needsReason = decision !== "approve"/);
  assert.match(portal, /reason: decision === "approve" \? "" : writtenReason/);
  assert.match(portal, /Veröffentlichung läuft/);
  assert.match(portal, /\/portal\/decision-jobs\?active=true/);
  assert.doesNotMatch(portal, /className="wp-decision-overlay"/);
  assert.doesNotMatch(portal, /while \(!\["completed", "failed"\]\.includes\(job\.status\)\)/);
  assert.match(portal, /Entscheidung wurde sicher angenommen/);
  assert.match(portal, /watchDecisionUntilFinished/);
  assert.match(portal, /await done\(\);[\s\S]*?window\.setTimeout/);
});

test("keeps draft publication controls unavailable and exposes the original", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /Original ansehen/);
  assert.match(portal, /href=\{doc\.original_url\}/);
  assert.match(portal, /doc\.status === "active"/);
  assert.match(portal, /Erst nach der Freigabe kannst du weitere Wissensbereiche zuordnen/);
  assert.match(portal, /Wissensbereich hinzufügen\?/);
  assert.match(portal, /Wissensbereich entfernen\?/);
  assert.match(portal, /Änderungen werden direkt gespeichert und im Audit-Verlauf dokumentiert/);
  assert.match(portal, /Veröffentlichung erneut versuchen/);
  assert.match(portal, /Technische Veröffentlichung fehlgeschlagen/);
  assert.match(portal, /task\.publication_error/);
  assert.match(portal, /decisionFeedback\[task\.case_id\][\s\S]*role="status"/);
  assert.match(portal, /reasonByDocument, setReasonByDocument/);
  assert.match(portal, /value=\{reasonByDocument\[doc\.document_id\] \|\| ""\}/);
  assert.match(portal, /\[doc\.document_id\]: e\.target\.value/);
  const documentList = portal.slice(portal.indexOf("function DocumentList("), portal.indexOf("function RemovalsPage("));
  assert.doesNotMatch(documentList, /\[reason, setReason\] = useState\(""\)/);
});

test("uses a clear saved user editor and combines absence with delegation", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /wp-user-admin-layout/);
  assert.match(portal, /Ungespeicherte Änderungen/);
  assert.match(portal, /Änderungen speichern/);
  assert.match(portal, /Abwesenheit und Vertretung wurden gemeinsam gespeichert/);
  assert.match(portal, /delegate_user_id:\s*delegate/);
  assert.match(portal, /Automatisch mit Outlook synchronisiert/);
  assert.doesNotMatch(portal, /<h2>Vertretungen<\/h2>/);
});

test("supports actionable knowledge-error reporting and quality-case handling", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /onPaste=\{pasteScreenshot\}/);
  assert.match(portal, /Datei auswählen/);
  assert.match(portal, /multiple/);
  assert.match(portal, /slice\(0, 5\)/);
  assert.match(portal, /Vielen Dank für deine Meldung/);
  assert.match(portal, /openQualityCases/);
  assert.match(portal, /id === "trash" && Boolean\(removals\.unread_count\)/);
  assert.match(portal, /\/portal\/admin\/trash\/read/);
  assert.match(portal, /Nutzer benachrichtigen/);
  assert.match(portal, /Fall gelöst/);
  assert.match(portal, /Screenshot ansehen/);
  assert.doesNotMatch(portal, /Danke\. Die Meldung wurde unter \$\{result\.feedback_id\}/);
});

test("offers searchable owner selection and human-readable audit entries", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /Name oder E-Mail suchen/);
  assert.match(portal, /entry\.event_label/);
  assert.match(portal, /entry\.subject_label/);
  assert.match(portal, /entry\.details_label/);
  assert.match(portal, /ausgeführt von \{entry\.actor_name\}/);
  assert.match(portal, /Auditprotokoll durchsuchen/);
  assert.match(portal, /Zu dieser Suche wurden keine Audit-Einträge gefunden/);
  assert.match(portal, /audit\?limit=1000/);
});

test("closes pickers outside, validates validity dates, and explains technical failures", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /closeOpenDropdowns/);
  assert.match(portal, /document\.querySelectorAll<HTMLDetailsElement>\("details\[open\]"\)/);
  assert.match(portal, /max=\{maximumValidUntil\}/);
  assert.match(portal, /Maximal 60 Tage sind möglich/);
  assert.match(portal, /Zugeordnete Vertretung/);
  assert.match(portal, /embedded_executable_content_not_allowed/);
  assert.match(portal, /diagnostic_json/);
});

test("offers searchable manager and delegate assignment", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /function SearchableUserPicker/);
  assert.match(portal, /Zugeordnete Führungskraft/);
  assert.match(portal, /Zugeordnete Vertretung/);
  assert.match(portal, /Name oder E-Mail suchen/);
  assert.match(portal, /Kein passender Benutzer gefunden/);
  assert.match(portal, /\["manager", "admin", "portal_admin"\]\.includes\(user\.role\)/);
});

test("shows version candidates to uploaders and reviewers", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /duplicate_matches/);
  assert.match(portal, /Als neue Version von/);
  assert.match(portal, /className="wp-version-action"/);
  assert.match(portal, /Vorhandenes Dokument prüfen/);
  assert.match(portal, /Als eigenständiges Dokument vorschlagen/);
  assert.match(portal, /Wirklich als eigenständiges Dokument anlegen/);
  assert.doesNotMatch(portal, /match\.version_candidate && !match\.has_conflict/);
});

test("shows the persistent upload queue and assigns technical cases to an upload", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /Meine laufenden Uploads/);
  assert.match(portal, /Position \$\{item\.position\}/);
  assert.match(portal, /Auftrags-ID:/);
  assert.match(portal, /Hochgeladen von:/);
  assert.match(portal, /Vorgesehener Owner:/);
  assert.match(portal, /Betroffener Seitenbereich:/);
  assert.match(portal, /upload_worker_interrupted/);
});

test("uses German upload messages and offers decisions for preparation review", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /failed:\s*"Verarbeitung fehlgeschlagen"/);
  assert.match(portal, /upload_worker_interrupted:\s*"Die Verarbeitung wurde unterbrochen/);
  assert.match(portal, /task\.status === "needs_correction"/);
  assert.match(portal, /Ablehnen/);
  assert.match(portal, /Weiterleiten/);
  assert.match(portal, /Freigeben/);
});

test("offers the version archive with restore only to admins", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.match(portal, /\["archive", "Versionsarchiv", Archive\]/);
  assert.match(portal, /tab === "archive" && isAdmin && \(/);
  assert.match(portal, /\/portal\/admin\/archive\/\$\{item\.version_id\}\/restore/);
  assert.match(portal, /\/portal\/admin\/archive\/\$\{item\.version_id\}\/source/);
  assert.match(portal, /Frühere Version wiederherstellen\?/);
  assert.match(portal, /Aktuell gültige Fassung/);
});
