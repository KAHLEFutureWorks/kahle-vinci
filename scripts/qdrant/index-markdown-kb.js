const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const kb = process.env.KB_NAME || "kahleallgemein";
const root = process.env.KB_ROOT || `/home/node/.n8n-files/knowledgebases/${kb}`;
const qdrant = process.env.QDRANT_URL || "http://qdrant:6333";
const collection = process.env.QDRANT_COLLECTION || kb;
const ionosBase = process.env.IONOS_OPENAI_BASE_URL || "https://openai.inference.de-txl.ionos.com/v1";
const model = process.env.IONOS_EMBEDDING_MODEL || "BAAI/bge-m3";
const apiKey = process.env.IONOS_API_KEY;

if (!apiKey) throw new Error("IONOS_API_KEY missing");

function uuidFrom(input) {
  const h = crypto.createHash("sha1").update(input).digest("hex");
  const variant = ((parseInt(h.slice(16, 18), 16) & 0x3f) | 0x80).toString(16).padStart(2, "0");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-${variant}${h.slice(18, 20)}-${h.slice(20, 32)}`;
}

function chunkText(text, max = 1800, overlap = 220) {
  const clean = text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  const chunks = [];
  let i = 0;
  while (i < clean.length) {
    let end = Math.min(clean.length, i + max);
    if (end < clean.length) {
      const cut = clean.lastIndexOf("\n\n", end);
      if (cut > i + 500) end = cut;
    }
    const part = clean.slice(i, end).trim();
    if (part) chunks.push(part);
    if (end >= clean.length) break;
    i = Math.max(end - overlap, i + 1);
  }
  return chunks;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { text };
  }
  if (!response.ok) {
    const message = `${options.method || "GET"} ${url} -> ${response.status}: ${text.slice(0, 300)}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}

async function embed(input) {
  const body = await requestJson(`${ionosBase}/embeddings`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model, input }),
  });
  const vector = body.data?.[0]?.embedding;
  if (!Array.isArray(vector) || vector.length !== 1024) {
    throw new Error(`unexpected embedding dimension: ${vector?.length || 0}`);
  }
  return vector;
}

async function ensureCollection() {
  try {
    await requestJson(`${qdrant}/collections/${collection}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vectors: { size: 1024, distance: "Cosine" } }),
    });
  } catch (error) {
    if (error.status !== 409) throw error;
  }
}

async function main() {
  await ensureCollection();

  const files = fs
    .readdirSync(root)
    .filter((file) => file.toLowerCase().endsWith(".md"))
    .sort();

  let total = 0;
  for (const file of files) {
    const fullPath = path.join(root, file);
    const sourcePath = file;
    const docId = `${kb}/${sourcePath}`;

    await requestJson(`${qdrant}/collections/${collection}/points/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filter: { must: [{ key: "doc_id", match: { value: docId } }] } }),
    });

    const text = fs.readFileSync(fullPath, "utf8");
    const chunks = chunkText(text);
    const points = [];

    for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
      const content = chunks[chunkIndex];
      const vector = await embed(content);
      points.push({
        id: uuidFrom(`${docId}#${chunkIndex}`),
        vector,
        payload: {
          content,
          text: content,
          kb,
          doc_id: docId,
          source_path: sourcePath,
          chunk_index: chunkIndex,
          metadata: {
            doc_id: docId,
            kb,
            source_path: sourcePath,
            chunk_index: chunkIndex,
            filename: file,
            source: "direct-indexer",
          },
        },
      });
    }

    if (points.length) {
      await requestJson(`${qdrant}/collections/${collection}/points?wait=true`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points }),
      });
    }

    console.log(`${file}: ${points.length} chunks indexed`);
    total += points.length;
  }

  const count = await requestJson(`${qdrant}/collections/${collection}/points/count`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ exact: true }),
  });
  console.log(`total indexed this run: ${total}; qdrant count: ${count.result?.count}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
