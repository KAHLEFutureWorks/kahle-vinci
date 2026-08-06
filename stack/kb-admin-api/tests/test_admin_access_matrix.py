import tempfile
from pathlib import Path

from test_document_lifecycle import setup


def test_admin_can_read_effective_user_access_matrix():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, kb_id = setup(Path(directory))
        access = governance.access_for_user("admin", "employee")
        assert access == [{
            "knowledgebase_id": kb_id, "label": "Service", "can_read": 1, "can_upload": 1,
        }]
