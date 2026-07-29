import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, root), "utf8");

test("renders the KAHLE Vector management surface", async () => {
  const [page, layout, dashboard, styles] = await Promise.all([
    source("app/page.tsx"), source("app/layout.tsx"),
    source("components/VectorAdmin.tsx"), source("app/vector.css"),
  ]);
  assert.match(page, /<VectorAdmin \/>/);
  assert.match(layout, /KAHLE Vector/);
  assert.match(dashboard, /Knowledge Management/);
  assert.match(dashboard, /Semantische Suche/);
  assert.match(dashboard, /Datei hochladen/);
  assert.match(dashboard, /Dateien hier ablegen/);
  assert.match(dashboard, /Neue Knowledge Base/);
  assert.match(dashboard, /availableMoveTargets/);
  assert.match(dashboard, /formatDate\(item\.valid_until\)/);
  assert.match(dashboard, /Speichern & neu indexieren/);
  assert.match(dashboard, /\/admin\/vector\/api/);
  assert.match(styles, /\.vector-app/);
  assert.match(styles, /grid-template-columns/);
});

test("keeps server credentials out of the dashboard bundle", async () => {
  const dashboard = await source("components/VectorAdmin.tsx");
  assert.doesNotMatch(dashboard, /IONOS_API_KEY|QDRANT_API_KEY/);
  assert.match(dashboard, /localStorage\.getItem\("token"\)/);
  assert.match(dashboard, /credentials:\s*"include"/);
});