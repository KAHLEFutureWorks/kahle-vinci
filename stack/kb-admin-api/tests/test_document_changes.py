import tempfile
from datetime import date
from pathlib import Path

from app.document_changes import DocumentChangeService
from test_document_lifecycle import SHA_B, SHA_C, lifecycle_module, setup, submit
from test_source_access import activate


def test_single_knowledgebase_renewal_requires_owner_confirmation_then_manager_only():
    with tempfile.TemporaryDirectory() as directory:
        governance,lifecycle,kb_id=setup(Path(directory)); active=activate(lifecycle,kb_id)
        ids=iter(("renewal-1",))
        service=DocumentChangeService(governance.store,governance,identifier=lambda:next(ids),today=lambda:date(2026,8,6))
        request=service.request_renewal(active.document_id,"employee","Inhalt weiterhin aktuell",True)
        assert service.pending_for("manager")[0]["request_id"]==request
        assert service.decide(request,"manager",True,"Fachlich bestätigt")=="approved"
        assert lifecycle.version_record(active.version_id)["valid_until"]=="2026-10-29"


def test_multi_knowledgebase_renewal_requires_manager_then_admin():
    with tempfile.TemporaryDirectory() as directory:
        governance,lifecycle,first_kb=setup(Path(directory))
        first=submit(lifecycle,first_kb)
        lifecycle.record_analysis(case_id=first.case_id,normalized_sha256=SHA_B,
                                  markdown_sha256=SHA_C,analysis=lifecycle_module.Analysis())
        lifecycle.decide(case_id=first.case_id,actor_user_id="manager",decision="approve",
                         reason="Fachlich bestätigt")
        first=lifecycle.activate(case_id=first.case_id)
        second_kb=governance.request_knowledgebase_change(
            "portal","create",payload={"slug":"verkauf","label":"Verkauf"},
        ).knowledgebase_id
        governance.grant_access("portal","employee",second_kb,can_read=True,can_upload=True)
        duplicate=lifecycle.submit(
            uploaded_by_user_id="employee",owner_user_id="employee",
            target_knowledgebase_id=second_kb,title="Arbeitsanweisung",
            original_filename="duplicate.docx",original_file_id="dup-file",
            original_sha256="d"*64,valid_workdays=60,confidentiality="restricted",
        )
        lifecycle.record_analysis(
            case_id=duplicate.case_id,normalized_sha256="e"*64,markdown_sha256="f"*64,
            analysis=lifecycle_module.Analysis(
                exact_duplicate_document_id=first.document_id,
                cross_kb_matches=(first.document_id,),
            ),
        )
        lifecycle.choose_action(case_id=duplicate.case_id,actor_user_id="employee",
                                action="publish_existing")
        lifecycle.decide(case_id=duplicate.case_id,actor_user_id="manager",decision="approve",
                         reason="Zusätzliche Veröffentlichung bestätigt")
        lifecycle.decide(case_id=duplicate.case_id,actor_user_id="admin",decision="approve",
                         reason="Bereichsübergreifend geprüft")
        lifecycle.publish_existing(case_id=duplicate.case_id)

        service=DocumentChangeService(
            governance.store,governance,identifier=lambda:"renewal-multi",
            today=lambda:date(2026,8,6),
        )
        request=service.request_renewal(
            first.document_id,"employee","Inhalt weiterhin aktuell",True,
        )
        assert service.decide(request,"manager",True,"Fachlich bestätigt")=="pending_admin"
        assert service.decide(request,"admin",True,"Bereichsübergreifend bestätigt")=="approved"


def test_owner_may_raise_confidentiality_but_downgrade_needs_admin():
    with tempfile.TemporaryDirectory() as directory:
        governance,lifecycle,kb_id=setup(Path(directory)); active=activate(lifecycle,kb_id)
        ids=iter(("raise-1","lower-1")); service=DocumentChangeService(governance.store,governance,identifier=lambda:next(ids))
        service.request_confidentiality(active.document_id,"employee","confidential","Schutz erhöhen")
        with governance.store.connect() as db: assert db.execute("SELECT confidentiality FROM canonical_documents WHERE document_id=?",(active.document_id,)).fetchone()[0]=="confidential"
        lower=service.request_confidentiality(active.document_id,"employee","internal","Nicht mehr vertraulich")
        assert service.pending_for("admin")[0]["request_id"]==lower
        service.decide(lower,"admin",True,"Herabstufung geprüft")
        with governance.store.connect() as db: assert db.execute("SELECT confidentiality FROM canonical_documents WHERE document_id=?",(active.document_id,)).fetchone()[0]=="internal"
