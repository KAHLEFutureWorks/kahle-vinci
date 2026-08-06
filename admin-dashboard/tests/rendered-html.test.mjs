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

test("keeps server credentials and direct vector access out of the portal bundle", async () => {
  const portal = await source("components/KnowledgePortal.tsx");
  assert.doesNotMatch(portal, /IONOS_API_KEY|QDRANT_API_KEY|QDRANT_URL/);
  assert.doesNotMatch(portal, /localStorage/);
  assert.doesNotMatch(portal, /\/collections\//);
});
