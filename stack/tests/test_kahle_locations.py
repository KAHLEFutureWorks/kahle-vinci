"""One canonical KAHLE location table (review decision 2026-10-07).

A new or renamed location is edited in ``stack/open-webui-tools/kahle_locations.py``
only. ``build_tools.py`` distributes it to the harness, the middleware, the tool
bundles and the toolcall guard, and ``--check`` reports any copy left behind.
"""

import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "open-webui-tools"
CANONICAL = TOOLS / "kahle_locations.py"
UTILS = ROOT / "open-webui-overrides" / "open_webui" / "utils"
GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"
CONSUMERS = (
    UTILS / "kahle_knowledge_harness.py",
    UTILS / "middleware.py",
    TOOLS / "hybrid_retrieval.py",
    TOOLS / "hybrid_retrieval_adapters.py",
    TOOLS / "rag_chat_hybrid_tool.py",
    TOOLS / "kahle_workflow_orchestrator.py",
    GUARD,
)
BLOCK = re.compile(r"# --- BEGIN kahle_locations .*?# --- END kahle_locations ---\n", re.S)


def _load(name, path, *extra_paths):
    for extra in extra_paths:
        sys.path.insert(0, str(extra))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        for extra in extra_paths:
            sys.path.remove(str(extra))
    return module


def canonical():
    return _load("kahle_locations_canonical", CANONICAL)


def test_canonical_table_describes_every_location_once():
    table = canonical()

    assert table.KAHLE_LOCATIONS == (
        "Hannover", "Wunstorf", "Wedemark", "Walsrode", "Neustadt", "Nienburg", "Stadthagen",
    )
    assert dict(table.KAHLE_LOCATION_CODES) == {
        "HAN": "Hannover", "WUN": "Wunstorf", "WED": "Wedemark", "WAL": "Walsrode",
        "NEU": "Neustadt am Rübenberge", "NIE": "Nienburg", "STA": "Stadthagen", "SHG": "Stadthagen",
    }
    assert "Neustadt am Rübenberge" in table.KAHLE_LOCATION_FULL_NAMES
    assert len(set(table.KAHLE_LOCATIONS)) == len(table.KAHLE_LOCATIONS)


@pytest.mark.parametrize("path", CONSUMERS, ids=lambda p: p.name)
def test_no_consumer_keeps_its_own_location_names(path):
    source = BLOCK.sub("", path.read_text(encoding="utf-8")).casefold()

    for name in canonical().KAHLE_LOCATIONS:
        assert name.casefold() not in source, f"{path.name} nennt {name} selbst"


def test_runtime_copy_and_guard_block_match_the_canonical_file():
    source = CANONICAL.read_text(encoding="utf-8")

    assert (UTILS / "kahle_locations.py").read_text(encoding="utf-8") == source
    block = BLOCK.search(GUARD.read_text(encoding="utf-8"))
    assert block, "Guard ohne generierten Standortblock"
    assert "KAHLE_LOCATION_TABLE = (" in block.group(0)


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.local-edge.yml"])
def test_runtime_copy_is_mounted_read_only_next_to_the_harness(compose_file):
    import yaml

    compose = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))
    target = "/app/backend/open_webui/utils/kahle_locations.py"
    mounts = compose["services"]["open-webui"]["volumes"]
    matching = [mount for mount in mounts if isinstance(mount, str) and f":{target}:" in mount]

    assert len(matching) == 1
    assert matching[0].endswith(f"/stack/open-webui-overrides/open_webui/utils/kahle_locations.py:{target}:ro")


def test_harness_reads_names_and_codes_from_the_table():
    sys.path.insert(0, str(TOOLS))
    try:
        harness = _load("kahle_harness_locations", UTILS / "kahle_knowledge_harness.py")
    finally:
        sys.path.remove(str(TOOLS))
    table = canonical()

    assert harness.KAHLE_LOCATIONS == table.KAHLE_LOCATIONS
    for code, full_name in table.KAHLE_LOCATION_CODES:
        assert harness.KNOWN_ALIASES[code] == full_name
    assert harness.resolve_query_aliases("Öffnungszeiten STA") == "Öffnungszeiten Stadthagen"


def test_tool_bundle_expands_every_code_and_knows_every_location():
    tool = _load("rag_tool_locations", TOOLS / "rag_chat_hybrid_tool.py", TOOLS)
    table = canonical()

    for code, full_name in table.KAHLE_LOCATION_CODES:
        assert tool._expand_kahle_query_aliases(f"Ablauf {code}") == f"Ablauf {code} ({full_name})"
    for full_name in table.KAHLE_LOCATION_FULL_NAMES:
        assert tool._clarification_for_query(f"Öffnungszeiten {full_name}") == ""
        assert tool._clarification_for_query(f"öffnungszeiten {full_name.casefold()}") == ""
    assert tool._clarification_for_query("Öffnungszeiten Ruebenberge") == ""
    assert tool._clarification_for_query("Öffnungszeiten?")


def test_retrieval_counts_every_location_for_opening_hours():
    retrieval = _load("retrieval_locations", TOOLS / "hybrid_retrieval.py", TOOLS)
    names = canonical().KAHLE_LOCATION_FULL_NAMES

    assert retrieval.opening_hours_all_locations_intent("Öffnungszeiten " + " ".join(names[:4]))
    assert not retrieval.opening_hours_all_locations_intent("Öffnungszeiten " + " ".join(names[:3]))
    assert retrieval.opening_hours_all_locations_intent("Öffnungszeiten Neustadt am Rübenberge, "
                                                        + ", ".join(names[:3]))


def test_guard_uses_the_generated_table():
    guard = _load("guard_locations", GUARD)

    assert guard.KAHLE_LOCATIONS == canonical().KAHLE_LOCATIONS


def load_builder():
    return _load("locations_builder", TOOLS / "build_tools.py")


def test_guard_block_is_replaced_between_its_markers():
    builder = load_builder()
    text = "a = 1\n# --- BEGIN kahle_locations (alt) ---\nALT = 1\n# --- END kahle_locations ---\nb = 2\n"

    updated = builder.replace_location_block(text, "NEU = 2\n")

    assert updated.startswith("a = 1\n# --- BEGIN kahle_locations")
    assert "NEU = 2\n# --- END kahle_locations ---\nb = 2\n" in updated
    assert "ALT" not in updated
    with pytest.raises(ValueError):
        builder.replace_location_block("ohne Marker\n", "NEU = 2\n")


@pytest.mark.parametrize("target", [
    "open-webui-overrides/open_webui/utils/kahle_locations.py",
    "open-webui-functions/kahle_toolcall_guard.py",
])
def test_builder_distributes_locations_and_detects_drift(tmp_path, monkeypatch, target):
    builder = load_builder()
    tools_dir = tmp_path / "stack/open-webui-tools"
    tools_dir.mkdir(parents=True)
    for source in TOOLS.glob("*.py"):
        shutil.copyfile(source, tools_dir / source.name)
    (tools_dir.parent / "open-webui-functions").mkdir()
    shutil.copyfile(GUARD, tools_dir.parent / "open-webui-functions" / GUARD.name)
    monkeypatch.setattr(builder, "TOOLS_DIR", tools_dir)

    monkeypatch.setattr(sys, "argv", ["build_tools.py"])
    assert builder.main() == 0
    monkeypatch.setattr(sys, "argv", ["build_tools.py", "--check"])
    assert builder.main() == 0

    path = tools_dir.parent / target
    drifted = path.read_text(encoding="utf-8").replace('"Stadthagen"', '"Stadthagn"', 1)
    assert drifted != path.read_text(encoding="utf-8")
    path.write_text(drifted, encoding="utf-8")
    assert builder.main() == 1
    assert path.read_text(encoding="utf-8") == drifted, "check must not rewrite drift"
