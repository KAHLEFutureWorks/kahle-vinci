from document_authority import DocumentAuthorityService
from test_document_lifecycle import setup


def test_admin_sets_authority_and_structured_relation(tmp_path):
    governance, lifecycle, kb = setup(tmp_path)
    first = lifecycle.submit(
        uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=kb,
        title="Alt", original_filename="a.md", original_file_id="a", original_sha256="a" * 64,
        valid_workdays=60, confidentiality="internal",
    )
    second = lifecycle.submit(
        uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=kb,
        title="Neu", original_filename="b.md", original_file_id="b", original_sha256="b" * 64,
        valid_workdays=60, confidentiality="internal",
    )
    service = DocumentAuthorityService(governance.store, governance, identifier=lambda: "rel-1")
    value = service.update("portal", second.document_id, "executive_policy", {"locations": ["KAHLE"]}, "Durch Admin geprüft")
    assert value["metadata"]["authority_level"] == 3
    relation_id = service.relate("portal", second.document_id, first.document_id, "supersedes", "", "Ersetzt die alte Fassung")
    assert relation_id == "rel-1"
    assert service.view("portal", second.document_id)["relations"][0]["relation_type"] == "supersedes"
