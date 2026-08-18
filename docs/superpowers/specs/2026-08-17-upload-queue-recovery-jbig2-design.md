# Upload-Queue-Recovery und JBIG2-Toleranz

## Ziel

Die produktive Upload-Warteschlange darf weder durch Altaufträge ohne Lease noch durch später ablaufende Leases stehen bleiben. PDF-Bilder mit nicht unterstützter JBIG2-Kompression dürfen die Textkonvertierung nicht abbrechen.

## Queue-Recovery

`UploadJobService.claim_next()` schließt innerhalb derselben `BEGIN IMMEDIATE`-Transaktion alle verwaisten `processing`-Aufträge ab. Verwaist sind Aufträge mit `lease_expires_at IS NULL` oder einer abgelaufenen Lease. Sie erhalten `status='failed'` und `error_code='upload_worker_interrupted'`. Der Claim liefert neben dem nächsten Job die Recovery-Datensätze an den Worker zurück, damit Qualitätsfälle, Benachrichtigungen und Spool-Bereinigung außerhalb der Queue-Schicht ausgeführt werden können.

Der Worker prüft bei jedem Schleifendurchlauf erneut. Damit werden Leases auch dann erkannt, wenn sie erst nach dem Workerstart ablaufen.

## JBIG2-Toleranz

Der Dokument-Worker greift auf `page.images` indexweise zu. Fehler beim Dekodieren eines einzelnen Bildes, insbesondere `Unsupported filter /JBIG2Decode`, überspringen nur dieses Bild. Extrahierter Seitentext und weitere dekodierbare Bilder bleiben erhalten. Ist das Gesamtergebnis leer, greift weiterhin die bestehende Fehlerbehandlung.

## Qualitätsfälle und Meldungen

Für automatisch abgeschlossene Upload-Jobs wird der vorhandene jobbezogene Incident- und Benachrichtigungspfad verwendet. Fehlende Altmetadaten werden toleriert. Ein Altauftrag blockiert die Queue auch dann nicht, wenn die nachgelagerte Meldung fehlschlägt.

## Verifikation

- Altauftrag ohne Lease wird abgeschlossen und der nächste Job beansprucht.
- Eine nach Workerstart ablaufende Lease wird später erkannt.
- Recovery erzeugt Incident und Nutzerbenachrichtigung.
- Ein nicht dekodierbares JBIG2-Bild lässt vorhandenen PDF-Text bestehen.
- Backend-, Dokument-Worker- und Dashboard-Suiten bleiben grün.
