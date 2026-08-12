import tempfile
from pathlib import Path

import pytest

from test_document_lifecycle import SHA_B, SHA_C, lifecycle_module, setup, submit


def activate(lifecycle, kb_id):
    case = submit(lifecycle, kb_id)
    lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
        analysis=lifecycle_module.Analysis(),
    )
    lifecycle.decide(
        case_id=case.case_id, actor_user_id="manager", decision="approve", reason="Fachlich geprüft"
    )
    return lifecycle.activate(case_id=case.case_id)


def test_only_active_current_version_with_readable_publication_is_a_source():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        active = activate(lifecycle, kb_id)
        record = lifecycle.source_record(active.version_id, "employee")
        assert record["document_id"] == active.document_id
        assert record["visible_knowledgebase_ids"] == [kb_id]

        governance.sync_identity(user_id="outsider", email="outsider@kahle.de", display_name="Extern")
        with pytest.raises(lifecycle_module.LifecycleError, match="source_read_access_required"):
            lifecycle.source_record(active.version_id, "outsider")


def test_superseded_version_is_not_exposed_to_normal_source_endpoint():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        first = activate(lifecycle, kb_id)
        second = submit(lifecycle, kb_id, sha="d" * 64, document_id=first.document_id)
        lifecycle.record_analysis(
            case_id=second.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(same_kb_similarity="very_high"),
        )
        lifecycle.choose_action(case_id=second.case_id, actor_user_id="employee", action="replace")
        lifecycle.decide(
            case_id=second.case_id, actor_user_id="manager", decision="approve", reason="Neue Version"
        )
        lifecycle.activate(case_id=second.case_id)
        with pytest.raises(lifecycle_module.LifecycleError, match="source_not_available"):
            lifecycle.source_record(first.version_id, "employee")
