# IONOS Model Hub

Der lokale Stack nutzt kuenftig den IONOS OpenAI-kompatiblen Endpunkt. Ollama und `kunden-sql-gateway` werden aus der Zielarchitektur entfernt; die restlichen Dienste bleiben lokal auf `localhost`.

## Endpunkt und Modelle

- OpenAI-compatible Base URL: `https://openai.inference.de-txl.ionos.com/v1`
- Chat-Modell: `mistralai/Mistral-Small-24B-Instruct`
- Reasoning-/Alternativmodell: `openai/gpt-oss-120b`
- Embedding-Modell: `BAAI/bge-m3`

## Embeddings und Reindex

Qdrant bleibt die lokale Vector-Datenbank. Durch den Wechsel auf `BAAI/bge-m3` muessen bestehende Collections neu indexiert werden, weil alte Embedding-Vektoren nicht mit dem neuen Modellraum kompatibel sind.

Empfohlener Ablauf:

1. Bestehende Qdrant-Daten sichern.
2. Knowledgebases mit `BAAI/bge-m3` neu einbetten.
3. Stichproben mit RAG-Referenzfragen aus `eval/rag/questions.yml` pruefen.
4. Erst danach alte Indizes oder Archivkopien entfernen.

## Open WebUI

Die Compose-Konfiguration setzt `ENABLE_PERSISTENT_CONFIG=False`, damit die IONOS- und RAG-Env-Werte nicht von alten PersistentConfig-Eintraegen aus dem bestehenden `open-webui` Volume uebersteuert werden. Open WebUI ist explizit auf Qdrant verdrahtet:

- `VECTOR_DB=qdrant`
- `QDRANT_URI=http://qdrant:6333`
- `RAG_EMBEDDING_ENGINE=openai`
- `RAG_EMBEDDING_MODEL=BAAI/bge-m3`

## n8n

HTTP-Request-Nodes verwenden den IONOS-Endpunkt direkt mit `Authorization: Bearer {{$env.IONOS_API_KEY}}`.

LangChain OpenAI Chat/Embedding Nodes brauchen zusaetzlich ein n8n-Credential vom Typ `openAiApi`. Die exportierten Workflows referenzieren dafuer `IONOS OpenAI Compatible` und setzen `options.baseURL` auf `https://openai.inference.de-txl.ionos.com/v1`. Beim Import muss dieses Credential in n8n angelegt oder gemappt werden; der API-Key wird nicht ins Repository geschrieben.

## Secrets

Keine echten Secrets im Repository ablegen. API-Keys, Passwoerter und Tokens werden ausserhalb des Projekts verwaltet.

Unter Windows ist der Windows Credential Manager die vorgesehene Secret-Quelle. Wenn ein einzelner Wert fuer den Credential Manager zu lang ist, nutzt das Secret-Skript automatisch eine DPAPI-verschluesselte Datei unter `%APPDATA%/KAHLE-Vinci/secrets`. Start- oder Betriebsroutinen lesen Secrets daraus und reichen sie nur zur Laufzeit als Umgebungsvariablen oder Parameter weiter. Doku, Skripte und Compose-Dateien duerfen keine Klartext-Secrets enthalten.
