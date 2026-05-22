# Professionelle Dokumentausgaben

KAHLE-Vinci erzeugt neue DOCX-, PDF- und PPTX-Dateien zentral ueber den `owui-file-proxy`. Die Assets liegen lokal unter `C:\kahle-vinci\assets` und werden im Container read-only nach `/assets` gemountet.

## Ablage

- Word-Vorlage: `assets/templates/docx/KAHLE-DOCX-VORLAGE.docx`
- PDF-Referenzvorlage: `assets/templates/pdf/KAHLE-PDF-VORLAGE.pdf`
- PowerPoint-Vorlage: `assets/templates/pptx/KAHLE-PPTX-Vorlage.pptx`
- PPTX-Layout-Metadaten: `assets/templates/pptx/kahle-pptx-layouts.json`
- Logos: `assets/brand/logos/`
- Farben/Fonts: `assets/brand/colors/kahle-brand.json`
- PowerPoint-Fuellbilder:
  - `assets/presentation-images/fuehrungsleitlinien/`
  - `assets/presentation-images/unternehmensinhalte/`
  - `assets/presentation-images/autohaus/`
  - `assets/presentation-images/neutral/`

## Laufzeit-Konfiguration

`stack/docker-compose.yml` setzt fuer den File-Proxy:

- `KAHLE_ASSETS_ROOT=/assets`
- `KAHLE_DOCX_TEMPLATE=/assets/templates/docx/KAHLE-DOCX-VORLAGE.docx`
- `KAHLE_PDF_TEMPLATE=/assets/templates/pdf/KAHLE-PDF-VORLAGE.pdf`
- `KAHLE_PPTX_TEMPLATE=/assets/templates/pptx/KAHLE-PPTX-Vorlage.pptx`
- `KAHLE_BRAND_CONFIG=/assets/brand/colors/kahle-brand.json`
- `KAHLE_LOGO_PRIMARY=/assets/brand/logos/kahle-vinci-logo.png`

## Verhalten

- `docx_create_save` nutzt die DOCX-Vorlage fuer Styles/Theme und ersetzt den Body durch den generierten Inhalt.
- `pdf_create_save` nutzt eine professionelle PDF-Ausgabe mit KAHLE-Farbwelt, Header, Footer und Logo. Wenn ReportLab im Container fehlt, faellt das Tool auf die einfache PDF-Ausgabe zurueck.
- `pptx_create_save` nutzt die PPTX-Vorlage als Startdeck, entfernt Beispiel-Folien und erzeugt Folien aus Markdown-Ueberschriften und Stichpunkten.
- `kahle_workflow_execute` kann Recherche/RAG/Web und Datei-Ausgabe in einem Toolcall verbinden. `output_format` kann `pdf`, `docx`, `pptx` oder `md` sein.

## Pflegehinweise

Die echten Office-/PDF-/Bildassets sind per `.gitignore` ausgeschlossen. Neue Assets koennen lokal ersetzt werden, ohne dass Secrets oder interne Designdateien ins Git gelangen. Nach Aenderungen am Asset-Ordner den File-Proxy neu starten, damit der Container die geaenderten Dateien sicher sieht.
