from __future__ import annotations

import sqlite3
from pathlib import Path

from app.openwebui import SQLiteOpenWebUIUserReader
from app.state import SQLiteProvisioningStateStore
from app.models import EligibleUser, InvalidUser


def make_webui_db(tmp_path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    path = tmp_path / "webui.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE user (id TEXT, name TEXT, email TEXT, role TEXT)")
        connection.executemany("INSERT INTO user VALUES (?, ?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()
    return path


def test_reader_returns_only_eligible_roles_with_normalized_identity(tmp_path: Path) -> None:
    database = make_webui_db(
        tmp_path,
        [
            ("pending-1", "Pending Person", "pending@kahle.de", "pending"),
            ("user-1", " Amal  Remo ", " AMAL@KAHLE.DE ", "user"),
            ("admin-1", "Jan Oltmanns", "jan@kahle.de", "admin"),
        ],
    )

    assert SQLiteOpenWebUIUserReader(database).eligible_users() == [
        EligibleUser("admin-1", "jan@kahle.de", "Jan", "Oltmanns", "admin"),
        EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user"),
    ]


def test_reader_reports_eligible_user_with_incomplete_name_as_invalid(tmp_path: Path) -> None:
    database = make_webui_db(
        tmp_path, [("user-1", "Amal", "amal@kahle.de", "user")]
    )
    reader = SQLiteOpenWebUIUserReader(database)

    assert reader.eligible_users() == []
    assert reader.invalid_users() == [InvalidUser("user-1", "amal@kahle.de", "invalid_name")]


def test_reader_converts_microsoft_surname_first_name_format(tmp_path: Path) -> None:
    database = make_webui_db(
        tmp_path, [("user-1", "Janssen.Jan", "janssen@kahle.de", "user")]
    )

    assert SQLiteOpenWebUIUserReader(database).eligible_users() == [
        EligibleUser("user-1", "janssen@kahle.de", "Jan", "Janssen", "user")
    ]


def test_reader_exposes_pending_requests_and_current_admins(tmp_path: Path) -> None:
    database = make_webui_db(
        tmp_path,
        [
            ("pending-1", "User.New", "new.user@kahle.de", "pending"),
            ("admin-1", "Admin.One", "admin.one@kahle.de", "admin"),
            ("user-1", "Regular.User", "regular.user@kahle.de", "user"),
        ],
    )
    reader = SQLiteOpenWebUIUserReader(database)

    assert reader.pending_users() == [
        EligibleUser("pending-1", "new.user@kahle.de", "New", "User", "pending")
    ]
    assert reader.admin_users() == [
        EligibleUser("admin-1", "admin.one@kahle.de", "One", "Admin", "admin")
    ]


def test_reader_reports_malformed_email_with_precise_error(tmp_path: Path) -> None:
    database = make_webui_db(
        tmp_path, [("user-1", "Amal Remo", "amal-at-kahle", "user")]
    )
    reader = SQLiteOpenWebUIUserReader(database)

    assert reader.eligible_users() == []
    assert reader.invalid_users() == [InvalidUser("user-1", "amal-at-kahle", "invalid_email")]


def test_state_records_completion_failure_and_heartbeat(tmp_path: Path) -> None:
    state = SQLiteProvisioningStateStore(tmp_path / "state.sqlite3")

    state.record_completed("user-1", "member-1", now_epoch=100)
    state.record_failure("user-2", "invalid_name", now_epoch=101)
    state.record_skipped("user-3", "learningsuite_team_member", now_epoch=101)
    state.record_welcome_sent("AMAL@KAHLE.DE", now_epoch=101)
    state.record_pending_notice_sent("pending-1", "ADMIN@KAHLE.DE", now_epoch=101)
    state.record_heartbeat(102)

    assert state.was_completed("user-1") is True
    assert state.member_id("user-1") == "member-1"
    assert state.last_error("user-2") == "invalid_name"
    assert state.was_handled("user-3") is True
    assert state.skipped_reason("user-3") == "learningsuite_team_member"
    assert state.welcome_was_sent("amal@kahle.de") is True
    assert state.pending_notice_was_sent("pending-1", "admin@kahle.de") is True
    assert state.heartbeat_epoch() == 102
