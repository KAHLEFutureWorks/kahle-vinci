import tempfile
import sys
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
from outlook_absence import sync_outlook_absences
from test_document_lifecycle import setup


class FakeGraphClient:
    def __init__(self, replies):
        self.replies = replies

    def automatic_replies(self, email):
        return self.replies.get(email, {"status": "disabled"})


def test_outlook_absence_sync_uses_existing_delegate_and_preserves_manual_entries():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        governance.assign_delegate(
            "admin", "manager", "employee", valid_from="2026-08-10", valid_until="2026-08-25",
        )
        graph = FakeGraphClient({
            "manager@kahle.de": {
                "status": "scheduled",
                "scheduledStartDateTime": {"dateTime": "2026-08-10T08:00:00"},
                "scheduledEndDateTime": {"dateTime": "2026-08-25T18:00:00"},
            },
        })

        result = sync_outlook_absences(governance.store, graph, today=date(2026, 8, 14))

        assert result["synced"] == 1
        absence = next(item for item in governance.list_absences("admin")
                       if item["manager_user_id"] == "manager")
        assert absence["source"] == "outlook"
        assert absence["delegate_user_id"] == "employee"
        assert absence["absent_from"] == "2026-08-10"
        assert absence["absent_until"] == "2026-08-25"

        governance.set_absence(
            "admin", "manager", "2026-08-12", "2026-08-20", "Manuell gepflegt", "employee",
        )
        result = sync_outlook_absences(governance.store, graph, today=date(2026, 8, 14))
        assert result["manual_preserved"] == 1
        absence = next(item for item in governance.list_absences("admin")
                       if item["manager_user_id"] == "manager")
        assert absence["source"] == "manual"
        assert absence["absent_from"] == "2026-08-12"


def test_outlook_absence_requires_a_portal_delegate():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        graph = FakeGraphClient({"manager@kahle.de": {"status": "alwaysEnabled"}})

        result = sync_outlook_absences(governance.store, graph, today=date(2026, 8, 14))

        assert result["delegate_required"] == 1
        assert governance.list_absences("admin") == []


if __name__ == "__main__":
    test_outlook_absence_sync_uses_existing_delegate_and_preserves_manual_entries()
    test_outlook_absence_requires_a_portal_delegate()
    print("graph portal integration tests passed")
