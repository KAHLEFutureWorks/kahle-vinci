# KAHLE-Vinci Wissensportal

Rollenbasierte Anwendung für Upload, Prüfung, Freigabe und Verwaltung der KAHLE-Vinci-Knowledge-Bases.

## Lokal starten

```bash
npm ci
npm run dev
```

Im vollständigen lokalen Stack wird die Anwendung über Caddy unter `http://localhost:3004/wissen/` bereitgestellt. Der Produktionspfad lautet `/wissen/`.

## Sicherheit

- Die UI enthält keine Qdrant- oder IONOS-Zugangsdaten.
- API-Aufrufe übernehmen die bestehende Open-WebUI-Sitzung.
- Die API prüft nach der OpenWebUI-Anmeldung die Portalrolle und die jeweiligen Knowledge-Base-Rechte.
- Quelldateien bleiben führend; `kb-sync` aktualisiert Qdrant.

Die vollständige Betriebsdokumentation liegt unter `docs/operations/kb-admin-dashboard.md`.
