from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"


def load_register():
    spec = importlib.util.spec_from_file_location("register_kahle_workflow", REGISTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def model_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """
        create table model (
            id text primary key, user_id text, base_model_id text, name text,
            meta text, params text, created_at integer, updated_at integer,
            is_active integer
        )
        """
    )
    con.execute(
        """
        insert into model values (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            "kahle-vinci-thinking",
            "owner-1",
            "openai/gpt-oss-120b",
            "KAHLE-Vinci-Thinking",
            json.dumps({"description": "thinking", "toolIds": ["rag_chat"]}),
            json.dumps({"system": "thinking prompt", "temperature": 0.2}),
            10,
            10,
        ),
    )
    return con


def test_max_registration_creates_hidden_base_and_custom_model_idempotently():
    register = load_register()
    con = model_db()

    first = register.ensure_max_vinci_models(con, now=20)
    second = register.ensure_max_vinci_models(con, now=30)

    assert first == {"base_created": True, "model_created": True}
    assert second == {"base_created": False, "model_created": False}
    base = con.execute(
        "select * from model where id = ?", (register.KAHLE_VINCI_MAX_BASE_MODEL_ID,)
    ).fetchone()
    maximum = con.execute(
        "select * from model where id = ?", (register.KAHLE_VINCI_MAX_MODEL_ID,)
    ).fetchone()
    assert base["base_model_id"] is None
    assert json.loads(base["meta"])["hidden"] is True
    assert maximum["base_model_id"] == register.KAHLE_VINCI_MAX_BASE_MODEL_ID
    assert maximum["name"] == "KAHLE-Vinci-Max-Thinking"
    assert json.loads(maximum["params"])["system"] == "thinking prompt"
    assert maximum["created_at"] == 20


def test_max_registration_preserves_an_existing_model_configuration():
    register = load_register()
    con = model_db()
    con.execute(
        "insert into model values (?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            register.KAHLE_VINCI_MAX_MODEL_ID,
            "owner-2",
            "custom/provider-model",
            "KAHLE-Vinci-Max-Thinking",
            json.dumps({"custom": True}),
            json.dumps({"system": "custom prompt"}),
            11,
            11,
        ),
    )

    result = register.ensure_max_vinci_models(con, now=20)

    maximum = con.execute(
        "select * from model where id = ?", (register.KAHLE_VINCI_MAX_MODEL_ID,)
    ).fetchone()
    assert result == {"base_created": True, "model_created": False}
    assert maximum["base_model_id"] == "custom/provider-model"
    assert json.loads(maximum["meta"]) == {"custom": True}
    assert json.loads(maximum["params"])["system"] == "custom prompt"


def test_max_base_and_model_are_in_the_public_registration_contract():
    register = load_register()

    assert register.KAHLE_VINCI_MAX_MODEL_ID in register.PUBLIC_MODEL_IDS
    assert register.KAHLE_VINCI_MAX_BASE_MODEL_ID in register.PUBLIC_MODEL_IDS
