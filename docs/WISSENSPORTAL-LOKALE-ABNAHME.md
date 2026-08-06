# Lokale Abnahme des KAHLE-Vinci Wissensportals

Stand: 6. August 2026

Dieses Protokoll ist die fortlaufende Nachweisakte zur lokalen Umsetzung des PRD. Eine Produktionsfreigabe ist damit ausdrücklich nicht verbunden.

## Automatisierte Nachweise

| Bereich | Nachweis | Ergebnis |
|---|---|---|
| Portal-Backend | `stack/kb-admin-api/tests` | 78 Tests bestanden |
| Stack, Verträge und Sicherheit | `stack/tests` | 238 Tests bestanden |
| Hybridindex und Synchronisierung | `stack/kb-sync/tests` | 10 Tests bestanden |
| Portal-UI | `npm test` in `admin-dashboard` | Build und 2 Rendering-/Sicherheitstests bestanden |
| Routing | `caddy validate` mit lokalen Platzhalterwerten | gültig |
| Orchestrierung | `docker compose config --quiet` mit lokalen Platzhalterwerten | gültig |
| Backup, Restore und Reindex | `stack/tests/test_portal_restore_reindex_e2e.py` | im Stack-Testlauf bestanden |

## Nachgewiesene Kerninvarianten

- Rollen, Knowledgebase-Rechte, Freigaben und Originaldateizugriff werden serverseitig geprüft.
- Der globale Dokumentvergleich ist unabhängig von den sichtbaren Knowledgebases des Uploaders.
- Exakte Dubletten werden blockiert; Knowledgebase-übergreifende Treffer und Widersprüche werden an Admins geleitet.
- Uploads laufen als persistente Hintergrundjobs und zeigen einen verständlichen Verarbeitungsstatus.
- Ein abweichender Dokument-Owner benötigt ein gesondertes Recht und muss die Übernahme ausdrücklich bestätigen.
- Führungskräfte, Vertretungen, Abwesenheiten sowie Eskalationen nach zwei, vier und sechs Arbeitstagen sind abgebildet.
- Malwareprüfung, Dateitypprüfung, Makro-/Verschlüsselungsblockade, Prompt-Injection-Prüfung und Konvertierungsprüfung laufen vor der Freigabe.
- PDF- und Office-Dokumente oberhalb der Grenze von 200 Seiten beziehungsweise geschätzten Druckseiten werden abgewiesen.
- Kontrolliertes RAG-Frontmatter ersetzt nicht vertrauenswürdige Upload-Metadaten.
- Autorität und strukturierte Beziehungen wie `supersedes` und `overrides` können ausschließlich administrativ mit Begründung gepflegt werden.
- Abgelaufene, zurückgezogene, gelöschte oder nicht aktive Versionen werden nicht an das Retrieval freigegeben.
- Erinnerungen, Papierkorb, Legal Hold, physische Löschung, Audit und verschlüsseltes Backup sind automatisiert abgedeckt.

## Noch offene Go-live-Nachweise

| Nachweis | Status | Nächster Schritt |
|---|---|---|
| Mindestens 90 Prozent richtige Treffer mit den vier KAHLE-Beispieldokumenten | blockiert durch lokalen IONOS-Token | gültigen IONOS-Token im lokalen `kb-sync` hinterlegen und `eval/rag/offline_hybrid_eval.py` ausführen |
| Mindestens 95 Prozent korrekt verlinkte Originalquellen | gemeinsam mit Retrieval-Evaluation offen | Bericht der Retrieval-Evaluation auswerten |
| Höchstens 5 Prozent unbelegte Antworten ohne freigegebene Quelle | Laufzeitevaluation offen | Negativfragen mit dem lokalen Vinci-Chat ausführen |
| 80 Prozent der Testmitarbeiter schaffen den Upload ohne Erklärung | organisatorischer Praxistest offen | kurze moderierte lokale Testrunde durchführen |
| Führungskräfte entscheiden Normalfälle durchschnittlich unter drei Minuten | organisatorischer Praxistest offen | Zeitmessung in derselben Testrunde durchführen |
| RPO 24 Stunden und RTO vier Stunden | technischer Restore bestanden, Zeitnachweis offen | vollständigen lokalen Restore mit Zeitmessung protokollieren |

## Aktueller externer Prüfblocker

Der im lokalen Container `kb-sync` konfigurierte IONOS-Token wurde am 6. August 2026 vom Embedding-Endpunkt mit HTTP 401 abgelehnt. Der Evaluationscode, der Fragensatz und die vier Beispieldokumente liegen lokal bereit. Zugangsdaten werden weder in diesem Protokoll noch in Evaluationsberichten gespeichert.

Der konfigurierte lokale TEI-Reranker ist im aktuellen Laufzeit-Stack noch nicht gestartet; das Image ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 ist lokal noch nicht vorhanden. Die Offline-Evaluation verwendet jetzt verpflichtend denselben Reranker-Endpunkt wie die Vinci-Laufzeit und bricht bei dessen Ausfall geschlossen ab.

Das Go-live-Gate bleibt geschlossen, bis alle offenen Nachweise erbracht und in dieser Datei dokumentiert sind.

## Nachweismatrix der 20 PRD-Abnahmeszenarien

| Nr. | Szenario | Nachweis | Stand |
|---:|---|---|---|
| 1 | DOCX hochladen, freigeben und Originalquelle öffnen | `test_docx_http_flow_activates_and_exposes_original_only_to_read_authorized_user` | automatisiert bestanden |
| 2 | Identische Datei blockieren | `test_exact_duplicate_is_blocked_and_only_publish_or_discard_is_allowed` und `test_global_analysis_sees_cross_kb_exact_duplicate` | automatisiert bestanden |
| 3 | Identisches Dokument in weiterer Knowledgebase veröffentlichen | `test_cross_kb_exact_duplicate_publishes_existing_canonical_document_only` | automatisiert bestanden |
| 4 | Neue Version atomar ersetzen und zurückrollen | `test_real_upload_is_bound_to_selected_version_candidate_before_replacement`, `test_new_version_atomically_supersedes_previous_active_version`, `test_failed_index_activation_restores_previous_active_version` | automatisiert bestanden |
| 5 | Ähnliche Dokumente verständlich vergleichen | `test_semantic_and_lexical_signals_are_combined_and_version_is_suggested` sowie Portal-Renderingtest | technisch automatisiert; Praxistest offen |
| 6 | Knowledgebase-übergreifenden Treffer direkt an Admin geben | `test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved` und `test_admin_queue_only_receives_escalated_case` | automatisiert bestanden |
| 7 | Widersprüchliche Richtlinien nicht automatisch veröffentlichen | derselbe Lifecycle-Test sowie `test_admin_sets_authority_and_structured_relation` | automatisiert bestanden |
| 8 | Prompt-Injection-Dokument in Quarantäne halten | `test_any_prompt_injection_signal_bypasses_employee_and_goes_directly_to_admin` und `test_embedded_executable_content_is_rejected_before_conversion` | automatisiert bestanden |
| 9 | Fehlerhafte Tabellen-/Excel-Konvertierung zeilen- und spaltenbezogen anzeigen und korrigieren | `test_conversion_quality_blocks_mojibake_and_flags_broken_tables`, `test_confirmed_employee_comment_creates_new_checked_draft_version`, Portal-Renderingtest | automatisiert bestanden |
| 10 | Owner bestätigt Aktualität; Führungskraft verlängert | `test_renewal_requires_owner_confirmation_then_manager_and_admin` | nach späterer Produktentscheidung zusätzlich mit Adminfreigabe automatisiert bestanden |
| 11 | Mehrfach veröffentlichtes Dokument durch Führungskraft und Admin verlängern | derselbe serverseitig verpflichtende zweistufige Verlängerungsworkflow | automatisiert bestanden |
| 12 | Abgelaufenes Dokument automatisch aus RAG entfernen | `test_expired_versions_are_removed_from_all_active_publications`, `test_expired_or_nonactive_document_can_never_be_activated` | automatisiert bestanden |
| 13 | Ohne Leserecht weder Antwortinhalt noch Originalquelle erhalten | `test_internal_scope_is_authenticated_and_derived_from_persisted_read_rights`, `test_hybrid_request_repeats_acl_in_both_prefetches_and_rejects_leak`, DOCX-HTTP-Test | automatisiert bestanden |
| 14 | Falsche Vinci-Antwort als Korrekturfall erfassen | `test_permission_feedback_is_critical_and_captures_effective_rights`, Portal-Feedbacktest | automatisiert bestanden |
| 15 | Deaktivierter Owner erzeugt Neuzuordnungsaufgabe | `test_deactivated_owner_creates_task_and_new_owner_must_confirm` | automatisiert bestanden |
| 16 | Admin bereitet Knowledgebase vor; Portal-Admin entscheidet | `test_admin_prepares_knowledgebase_change_portal_admin_decides` | automatisiert bestanden |
| 17 | Portal-Admin legt Knowledgebase direkt an | derselbe Governance-Test und HTTP-Vertrag | automatisiert bestanden |
| 18 | Dokument innerhalb von 30 Tagen wiederherstellen | `test_employee_removal_request_requires_admin_and_restore_reactivates_valid_version` | automatisiert bestanden |
| 19 | Nach 90 Tagen physisch löschen und Audit behalten | `test_trash_reminders_and_physical_deletion_at_day_90` | automatisiert bestanden |
| 20 | Vollständiger Restore und Indexneuaufbau | `test_encrypted_restore_rebuilds_authoritative_hybrid_index` | automatisiert bestanden |

Die technischen Abläufe aller 20 Szenarien besitzen damit konkrete automatisierte Nachweise. Szenario 5 benötigt zusätzlich den im Go-live-Gate geforderten Mitarbeiter-Praxistest; die messbare Retrieval-Qualität wird separat durch den KAHLE-Fragensatz nachgewiesen.
