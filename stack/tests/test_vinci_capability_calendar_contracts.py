from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPTS = [
    ROOT / "stack" / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "stack" / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
]
REGISTER = ROOT / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"
MIDDLEWARE = ROOT / "stack" / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"
COMPOSE = ROOT / "stack" / "docker-compose.yml"


def test_vinci_prompts_truthfully_disable_unavailable_capabilities():
    for path in PROMPTS:
        prompt = path.read_text(encoding="utf-8")
        assert "Verfuegbare Faehigkeiten wahrheitsgemaess beschreiben" in prompt
        assert "3.8 Bildgenerierung" not in prompt
        assert "3.8 Code-Interpreter und Terminal" not in prompt
        assert "Behaupte oder verspreche diese Funktionen niemals" in prompt


def test_all_three_vinci_models_are_hardened_on_every_registration():
    source = REGISTER.read_text(encoding="utf-8")
    assert '"kahle-vinci-max-thinking"' in source
    assert 'capabilities["image_generation"] = False' in source
    assert 'capabilities["code_interpreter"] = False' in source
    assert 'capabilities["terminal"] = False' in source
    assert 'builtin_tools["image_generation"] = False' in source
    assert 'builtin_tools["code_interpreter"] = False' in source


def test_calendar_creation_has_prompt_and_execution_guards():
    register = REGISTER.read_text(encoding="utf-8")
    middleware = MIDDLEWARE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    for prompt_path in PROMPTS:
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "Erstelle niemals sofort einen Kalendereintrag" in prompt
        assert "Soll ich diesen Termin jetzt im internen OpenWebUI-Kalender erstellen?" in prompt
        assert "keine Teilnehmer oder Einladungen" in prompt
    assert "create_calendar_event is a two-step write operation" in register
    assert "create_calendar_event is a two-step write operation" in compose
    assert "def _calendar_create_validation_error" in middleware
    assert "KALENDER_TOOLCALL_BLOCKIERT" in middleware
    assert "KALENDER_BESTAETIGUNG_ERFORDERLICH" in middleware
