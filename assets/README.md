# KAHLE-Vinci Assets

Lokale Ablage fuer Vorlagen, Logos und Bildmaterial, das die File-Tools fuer professionellere DOCX-, PDF- und PPTX-Ausgaben verwenden.

## Struktur

- `templates/docx/KAHLE-DOCX-VORLAGE.docx` - Word-Vorlage fuer neue DOCX-Berichte.
- `templates/pdf/KAHLE-PDF-VORLAGE.pdf` - PDF-Referenzvorlage fuer Layout/Farbwelt.
- `templates/pptx/KAHLE-PPTX-Vorlage.pptx` - PowerPoint-Vorlage fuer neue Praesentationen.
- `templates/pptx/kahle-pptx-layouts.json` - maschinenlesbare Vorgaben fuer Folientypen und Bildkategorien.
- `brand/logos/` - Logos als PNG/JPG, lokal nicht in Git.
- `brand/colors/kahle-brand.json` - Farb- und Schriftvorgaben.
- `presentation-images/` - optionale Fuellbilder nach Themen.

## Wichtig

Die eigentlichen Office-, PDF- und Bilddateien sind per `.gitignore` ausgeschlossen. Lege hier nur freigegebene Assets ab. Docker bindet diesen Ordner spaeter read-only in den File-Proxy ein.
