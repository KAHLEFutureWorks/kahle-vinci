import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, root), "utf8");

test("renders the role-based KAHLE-Vinci knowledge portal", async () => {
  const [page, portal, styles, dockerfile] = await Promise.all([
    source("app/page.tsx"), source("components/KnowledgePortal.tsx"),
    source("app/portal.css"), source("Dockerfile"),
  ]);
  assert.match(page, /<KnowledgePortal \/>/);
  assert.match(portal, /Dokument bereitstellen/);
  assert.match(portal, /Datei hier ablegen/);
  assert.match(portal, /Dokument-Owner/);
  assert.match(portal, /portal\/upload-jobs/);
  assert.match(portal, /Abwesenheiten/);
  assert.match(portal, /anderen aktiven Owner vorschlagen/);
  assert.match(portal, /Meine Vorgänge/);
  assert.match(portal, /Admin-Aufgaben/);
  assert.match(portal, /Benutzer & Rechte/);
  assert.match(portal, /portal\/auth\/step-up\/start/);
  assert.match(portal, /credentials: "include"/);
  assert.match(portal, /\/wissen\/api/);
  assert.doesNotMatch(portal, /Qualit\?|Pr\?fung|F\?hr|G\?lt|L\?sch|\?nder|\?ber|\?ff/);
  assert.match(styles, /\.wp-shell/);
  assert.match(styles, /@media/);
  assert.match(dockerfile, /DASHBOARD_BASE_PATH=\/wissen/);
});

test("meets the PRD accessibility and plain-language requirements", async () => {
  const [portal, styles] = await Promise.all([
    source("components/KnowledgePortal.tsx"), source("app/portal.css"),
  ]);

  // PRD 26.3: erkennbare Fokuszustände und Tastaturbedienung.
  assert.match(styles, /:focus-visible\{[^}]*outline:/);
  assert.match(portal, /onKeyDown=\{selectionKeys\(/);
  assert.match(portal, /role="button" tabIndex=\{0\}/);
  // Die Benutzerauswahl ist ein echter Button statt eines klickbaren <article>.
  assert.match(portal, /className="wp-pick" aria-pressed=/);
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
  assert.match(portal, /nameOf\(entry\.actor_user_id\)/);
  // Kein rohes JSON im Qualitätsdashboard.
  assert.doesNotMatch(portal, /<pre>\{JSON\.stringify/);
  // Dokumentkacheln lassen sich wieder schließen.
  assert.match(portal, /current === documentId \? "" : documentId/);

  // Adminübersicht: Wissensbereiche mit ihren Dokumenten, aufklappbar.
  assert.match(portal, /portal\/admin\/knowledgebase-overview/);
  assert.match(portal, /className="wp-kb-head" aria-expanded=/);
  assert.match(styles, /\.wp-kb-overview\{/);

  // PRD 26.2: keine Fachbegriffe für normale Nutzer.
  assert.match(portal, /confidentialityText\[result\.confidentiality\]/);
  assert.match(portal, /isAdmin \? "RAG-Markdown bearbeiten" : "Aufbereitete Fassung"/);
});

test("keeps server credentials and direct vector access out of the portal bundle", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.doesNotMatch(portal, /IONOS_API_KEY|QDRANT_API_KEY|QDRANT_URL/);
  assert.doesNotMatch(portal, /localStorage/);
  assert.doesNotMatch(portal, /\/collections\//);
});
