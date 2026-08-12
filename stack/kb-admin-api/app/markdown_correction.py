from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import requests

try:
    from .document_lifecycle import Analysis, DocumentLifecycle, LifecycleError, Submission
    from .global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from .portal_governance import PortalGovernance
    from .secure_ingest import PromptInjectionInspector, QuarantineStorage
except ImportError:  # pragma: no cover
    from document_lifecycle import Analysis, DocumentLifecycle, LifecycleError, Submission
    from global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from portal_governance import PortalGovernance
    from secure_ingest import PromptInjectionInspector, QuarantineStorage


class MarkdownCorrectionError(ValueError):
    pass


class IonosMarkdownCorrector:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def correct(self, markdown: str, instruction: str) -> str:
        if not self.api_key:
            raise MarkdownCorrectionError("correction_model_not_configured")
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "temperature": 0, "messages": [
                {"role": "system", "content": "Überarbeite RAG-Markdown ausschließlich entsprechend der freigegebenen Korrekturanweisung. Erhalte Fakten, Tabellen, Überschriften und Quellen. Gib nur vollständiges Markdown zurück."},
                {"role": "user", "content": f"KORREKTURANWEISUNG:\n{instruction}\n\nMARKDOWN:\n{markdown}"},
            ]}, timeout=self.timeout,
        )
        response.raise_for_status()
        corrected = str(response.json()["choices"][0]["message"]["content"]).strip()
        if corrected.startswith("```"):
            corrected = corrected.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if not corrected:
            raise MarkdownCorrectionError("correction_result_empty")
        return corrected + "\n"


class MarkdownCorrectionService:
    def __init__(self, governance: PortalGovernance, lifecycle: DocumentLifecycle,
                 analyzer: GlobalDocumentAnalyzer, corpus: GlobalCorpus, storage: QuarantineStorage,
                 corrector: IonosMarkdownCorrector | None = None,
                 restricted_term_matcher: Callable[[str], tuple[str, ...]] | None = None):
        self.governance, self.lifecycle, self.analyzer, self.corpus = governance, lifecycle, analyzer, corpus
        self.storage, self.corrector = storage, corrector
        self.injection = PromptInjectionInspector()
        self.restricted_term_matcher = restricted_term_matcher or (lambda _text: ())

    def review(self, case_id: str, actor_user_id: str) -> dict[str, Any]:
        case = self.lifecycle.submission(case_id); actor = self.governance.identity(actor_user_id)
        allowed = actor.role in {"admin", "portal_admin"} or actor_user_id in {
            case.uploaded_by_user_id, case.owner_user_id, case.manager_user_id,
        }
        if not allowed:
            raise MarkdownCorrectionError("case_review_forbidden")
        markdown_path = self.storage.root / case.document_id / case.version_id / "rag.md"
        if not markdown_path.is_file():
            raise MarkdownCorrectionError("markdown_not_available")
        return {"case": case, "markdown": markdown_path.read_text(encoding="utf-8"),
                "original_url": f"/wissen/api/portal/cases/{case_id}/original"}

    def revise(self, case_id: str, actor_user_id: str, *, instruction: str = "",
               replacement_markdown: str = "", reason: str, confirmed: bool) -> Submission:
        if not confirmed:
            raise MarkdownCorrectionError("correction_confirmation_required")
        old = self.lifecycle.submission(case_id); actor = self.governance.identity(actor_user_id)
        is_admin = actor.role in {"admin", "portal_admin"}
        if not is_admin and actor_user_id not in {old.uploaded_by_user_id, old.owner_user_id}:
            raise MarkdownCorrectionError("correction_forbidden")
        if len(reason.strip()) < 3:
            raise MarkdownCorrectionError("correction_reason_required")
        reviewed = self.review(case_id, actor_user_id)
        if replacement_markdown:
            if not is_admin:
                raise MarkdownCorrectionError("admin_markdown_override_required")
            corrected = replacement_markdown.strip() + "\n"
        else:
            if len(instruction.strip()) < 3 or not self.corrector:
                raise MarkdownCorrectionError("correction_instruction_required")
            corrected = self.corrector.correct(reviewed["markdown"], instruction.strip())
        finding = self.injection.inspect(corrected)
        old_root = self.storage.root / old.document_id / old.version_id
        originals = list(old_root.glob("original.*"))
        if len(originals) != 1:
            raise MarkdownCorrectionError("original_not_available")
        submission = self.lifecycle.submit(
            uploaded_by_user_id=actor_user_id, owner_user_id=old.owner_user_id,
            target_knowledgebase_id=old.target_knowledgebase_id, title=old.title,
            original_filename=old.original_filename, original_file_id=f"revision://{old.version_id}",
            original_sha256=old.original_sha256, valid_workdays=old.valid_workdays,
            confidentiality=old.confidentiality, document_id=old.document_id,
        )
        original = self.storage.store(submission.document_id, submission.version_id,
                                      originals[0].suffix.lstrip("."), originals[0].read_bytes())
        self.storage.store_markdown(original, corrected)
        result = self.analyzer.analyze(version_id=submission.version_id, title=submission.title, markdown=corrected)
        revised = self.lifecycle.record_analysis(
            case_id=submission.case_id, normalized_sha256=result.normalized_sha256,
            markdown_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
            analysis=Analysis(
                exact_duplicate_document_id=result.exact_document_id,
                cross_kb_matches=tuple(match.document_id for match in result.matches
                    if old.target_knowledgebase_id not in match.knowledgebase_ids),
                contradiction_document_ids=result.contradiction_document_ids,
                prompt_injection_risk=finding.risk,
                restricted_terms=self.restricted_term_matcher(corrected),
            ), actor_user_id=actor_user_id,
        )
        self.corpus.upsert(CorpusDocument(revised.document_id, revised.version_id, revised.title,
                                          corrected, (old.target_knowledgebase_id,), "pending"))
        with self.governance.store.connect() as db:
            db.execute(
                "INSERT INTO document_events(case_id, actor_user_id, event_type, details_json, created_at) VALUES (?, ?, 'markdown_revised', ?, ?)",
                (revised.case_id, actor_user_id, json.dumps({"reason": reason.strip()}, ensure_ascii=False), self.lifecycle.now()),
            )
        return revised
