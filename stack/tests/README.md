# File-Proxy Smoke Tests

Run from repository root (`c:\kahle-vinci` / project root).

Required: running stack with `open-webui`, `owui-file-proxy`, `document-worker`.

## PowerShell

```powershell
python stack/tests/smoke_file_proxy.py `
  --base-url http://127.0.0.1:8091 `
  --docx-file 75679381-38ab-4cb2-ba9e-3669eff4736d_test.docx `
  --pdf-file-a 8b172815-138b-4c81-b96c-5b5a6931c733_merged.pdf `
  --pdf-file-b 720b7f5d-8956-40e4-bca4-6123ec1d919d_merged.pdf `
  --txt-file f06422bb-9371-408a-b1b0-ad71ae715ac9_test.txt `
  --xlsx-file 59151290-9eaf-4a5b-9647-76f412531a74_test.xlsx `
  --xlsx-sheet Beispieldaten
```

## Bash

```bash
python stack/tests/smoke_file_proxy.py \
  --base-url http://127.0.0.1:8091 \
  --docx-file 75679381-38ab-4cb2-ba9e-3669eff4736d_test.docx \
  --pdf-file-a 8b172815-138b-4c81-b96c-5b5a6931c733_merged.pdf \
  --pdf-file-b 720b7f5d-8956-40e4-bca4-6123ec1d919d_merged.pdf \
  --txt-file f06422bb-9371-408a-b1b0-ad71ae715ac9_test.txt \
  --xlsx-file 59151290-9eaf-4a5b-9647-76f412531a74_test.xlsx \
  --xlsx-sheet Beispieldaten
```

