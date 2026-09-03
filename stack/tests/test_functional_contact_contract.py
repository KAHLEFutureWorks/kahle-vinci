"""Public contract regressions; all contact values are synthetic."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "open-webui-tools/functional_contact_contract.py"
HEADER = "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |"
SEPARATOR = "| --- | --- | --- | --- | --- |"
ROW = "| Marketing | E-Mail | marketing@example.invalid | Marketinganfragen | gruppenweit |"


def load_contract():
    assert SOURCE.is_file(), "canonical functional contact contract is missing"
    spec = importlib.util.spec_from_file_location("functional_contact_contract", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document(*rows, heading="## Funktionskontakte"):
    return "\n".join((heading, HEADER, SEPARATOR, *rows))


def expected_record():
    return {
        "schema_version": "kahle.functional-contact.v1",
        "function": "Marketing", "channel": "email",
        "value": "marketing@example.invalid", "purpose": "Marketinganfragen",
        "scope": "gruppenweit", "row_number": 4, "evidence_span": ROW,
    }


def test_exact_functional_contact_row():
    contract = load_contract()
    assert contract.parse_functional_contacts(document(ROW)) == (expected_record(),)
    assert contract.validate_functional_contact(expected_record()) == expected_record()
    assert contract.functional_contact_key(expected_record()) == (
        "Marketing", "email", "Marketinganfragen", "gruppenweit",
    )


@pytest.mark.parametrize("label,value,channel", [
    ("E-Mail", "it@example.invalid", "email"),
    ("Telefon", "+49 30 5550100", "phone"),
    ("Kontaktseite", "https://support.example.invalid/tickets", "url"),
])
def test_each_channel_retains_exact_value(label, value, channel):
    records = load_contract().parse_functional_contacts(document(
        f"| IT | {label} | {value} | Störungen | gruppenweit |",
    ))
    assert len(records) == 1
    assert records[0]["value"] == value
    assert records[0]["channel"] == channel


@pytest.mark.parametrize("label,value", [
    ("email", "it@example.invalid"),
    ("E-Mail", "not-an-email"),
    ("E-Mail", "a@example.invalid b@example.invalid"),
    ("E-Mail", "[IT](mailto:it@example.invalid)"),
    ("E-Mail", "<it@example.invalid>"),
    ("Telefon", "03.09.2026"),
    ("Telefon", "123"),
    ("Kontaktseite", "http://support.example.invalid"),
    ("Kontaktseite", "https://user:password@example.invalid"),
    ("Kontaktseite", "https:///tickets"),
    ("Kontaktseite", "https://example.invalid/a b"),
    ("Kontaktseite", "javascript:alert(1)"),
])
def test_invalid_contact_value_never_authorizes_row(label, value):
    bad = f"| IT | {label} | {value} | Störungen | gruppenweit |"
    records = load_contract().parse_functional_contacts(document(bad, ROW))
    assert len(records) == 1
    assert records[0]["value"] == "marketing@example.invalid"
    assert records[0]["row_number"] == 5


@pytest.mark.parametrize("text", [
    document(ROW, heading="## Kontakte"),
    document(ROW).replace("Kontaktwert", "Adresse"),
    document(ROW).replace(SEPARATOR, "| -- | --- | --- | --- | --- |"),
    document(ROW.replace("Marketinganfragen", "")),
    document(ROW.replace(" | gruppenweit |", " | gruppenweit | extra |")),
    "```markdown\n" + document(ROW) + "\n```",
    "~~~~\n" + document(ROW) + "\n~~~~",
])
def test_non_contract_blocks_are_not_contact_sources(text):
    assert load_contract().parse_functional_contacts(text) == ()


@pytest.mark.parametrize("hint", ["Für Fragen wie", "Beispielanfragen", "Suchbegriffe", "Synonyme", "Kurzindex"])
def test_hint_ancestor_cannot_grant_contact_authority(hint):
    assert load_contract().parse_functional_contacts(f"# {hint}\n" + document(ROW)) == ()


def test_heading_scope_ends_and_fenced_headings_do_not_change_it():
    text = document(ROW) + "\n## Anderes\n" + HEADER + "\n" + SEPARATOR + "\n" + ROW
    assert len(load_contract().parse_functional_contacts(text)) == 1
    text = "```\n# Kurzindex\n```\n" + document(ROW)
    records = load_contract().parse_functional_contacts(text)
    assert len(records) == 1
    assert records[0]["row_number"] == 7


def test_crlf_and_outer_whitespace_preserve_canonical_row():
    records = load_contract().parse_functional_contacts(document(ROW).replace("\n", "\r\n"))
    assert records == (expected_record(),)


def test_overlong_row_rejected_without_losing_next_valid_row():
    long_row = ROW.replace("Marketinganfragen", "x" * 901)
    records = load_contract().parse_functional_contacts(document(long_row, ROW))
    assert len(records) == 1
    assert records[0]["value"] == "marketing@example.invalid"


@pytest.mark.parametrize("change", [
    {"Value": "other@example.invalid"},
    {"value": ["marketing@example.invalid"]},
    {"row_number": True},
    {"row_number": 0},
    {"schema_version": "unknown"},
    {"channel": "url"},
    {"function": "Other"},
    {"evidence_span": ROW.replace("marketing@", "other@")},
])
def test_tampered_record_is_rejected(change):
    record = expected_record()
    record.update(change)
    assert load_contract().validate_functional_contact(record) is None


def test_missing_field_and_non_mapping_are_rejected():
    record = expected_record()
    del record["purpose"]
    contract = load_contract()
    assert contract.validate_functional_contact(record) is None
    assert contract.validate_functional_contact(ROW) is None


def test_literal_extraction_is_not_authorization_and_sees_link_targets():
    values = load_contract().extract_contact_literals(
        "Mail [Team](mailto:it@example.invalid), Telefon +49 30 5550100; "
        "[Portal](https://support.example.invalid/tickets). Datum 03.09.2026."
    )
    assert ("email", "it@example.invalid") in values
    assert ("phone", "+49 30 5550100") in values
    assert ("url", "https://support.example.invalid/tickets") in values
    assert ("phone", "03.09.2026") not in values


def load_builder():
    spec = importlib.util.spec_from_file_location("contact_bundle_builder", SOURCE.with_name("build_tools.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_embeds_contract_without_runtime_module_import(tmp_path, monkeypatch):
    builder = load_builder()
    shutil.copyfile(SOURCE, tmp_path / SOURCE.name)
    (tmp_path / "example_tool.py").write_text(
        "from functional_contact_contract import parse_functional_contacts\n"
        "def contacts(text):\n    return parse_functional_contacts(text)\n", encoding="utf-8",
    )
    monkeypatch.setattr(builder, "TOOLS_DIR", tmp_path)
    bundle = builder.build("example_tool.py", (SOURCE.name,))
    namespace = {"__name__": "isolated_tool"}
    exec(compile(bundle, "isolated_tool", "exec"), namespace)
    assert namespace["contacts"](document(ROW)) == (expected_record(),)


@pytest.mark.parametrize("copy_path", [
    "kb-sync/app/functional_contact_contract.py",
    "open-webui-overrides/open_webui/utils/functional_contact_contract.py",
])
def test_builder_generates_exact_copies_and_detects_drift(tmp_path, monkeypatch, copy_path):
    builder = load_builder()
    tools_dir = tmp_path / "stack/open-webui-tools"
    tools_dir.mkdir(parents=True)
    for source in SOURCE.parent.glob("*.py"):
        shutil.copyfile(source, tools_dir / source.name)
    monkeypatch.setattr(builder, "TOOLS_DIR", tools_dir)
    monkeypatch.setattr(sys, "argv", ["build_tools.py"])
    assert builder.main() == 0
    target = tools_dir.parent / copy_path
    assert target.is_file(), "runtime contract copy missing"
    assert target.read_bytes() == SOURCE.read_bytes()
    monkeypatch.setattr(sys, "argv", ["build_tools.py", "--check"])
    assert builder.main() == 0
    target.write_bytes(target.read_bytes() + b"\n# drift\n")
    assert builder.main() == 1
    assert target.read_bytes().endswith(b"# drift\n"), "check must not rewrite drift"


def test_contract_override_mount_is_read_only():
    import yaml

    compose = yaml.safe_load((SOURCE.parents[1] / "docker-compose.yml").read_text(encoding="utf-8"))
    target = "/app/backend/open_webui/utils/functional_contact_contract.py"
    mounts = compose["services"]["open-webui"]["volumes"]
    matching = [mount for mount in mounts if isinstance(mount, str) and f":{target}:" in mount]
    assert len(matching) == 1
    assert matching[0].endswith(":" + target + ":ro")
