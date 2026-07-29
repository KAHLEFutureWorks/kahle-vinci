# KAHLE Vector Admin-Dashboard

Interne Verwaltungsoberfläche für die Quelldateien der KAHLE-Vinci-Knowledgebases und ihren daraus erzeugten Qdrant-Index.

## Lokal starten

```bash
npm ci
npm run dev
```

Ohne erreichbare Admin-API zeigt `localhost` bewusst einen Demo-Datensatz. In Produktion wird das Dashboard unter `/admin/vector/` gebaut und ausschließlich über Caddy bereitgestellt.

## Sicherheit

- Die UI enthält keine Qdrant- oder IONOS-Zugangsdaten.
- API-Aufrufe übernehmen die bestehende Open-WebUI-Sitzung.
- Die API erlaubt ausschließlich Open-WebUI-Administratoren.
- Quelldateien bleiben führend; `kb-sync` aktualisiert Qdrant.

Die vollständige Betriebsdokumentation liegt unter `docs/operations/kb-admin-dashboard.md`.