from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "open-webui-prompts" / "vincis"
REGISTER_SCRIPT = ROOT.parents[0] / "scripts" / "openwebui" / "register-vinci-models.py"


VINCI_PROMPTS = [
    "kahle-email-vinci-systemprompt.md",
    "kahle-newsletter-vinci-systemprompt.md",
    "kahle-serviceberater-vinci-systemprompt.md",
    "kahle-angebotsmail-vinci-systemprompt.md",
    "kahle-beschwerde-vinci-systemprompt.md",
    "kahle-onboarding-vinci-systemprompt.md",
    "kahle-werkstatt-tagesbriefing-vinci-systemprompt.md",
    "kahle-richtlinien-vinci-systemprompt.md",
]


def test_all_vinci_prompts_handle_empty_starter_prompts():
    for file_name in VINCI_PROMPTS:
        prompt = (PROMPTS / file_name).read_text(encoding="utf-8")

        assert "Leere Starter-Prompts" in prompt, file_name
        assert "OpenWebUI-Vorschlaege koennen direkt als Nutzernachricht abgeschickt werden" in prompt, file_name
        assert "erfinde" in prompt.lower(), file_name
        assert "Antworte kurz und ausschliesslich als Rueckfrage" in prompt, file_name


def test_registered_suggestion_prompts_start_guided_input_flow():
    script = REGISTER_SCRIPT.read_text(encoding="utf-8")
    old_direct_starters = [
        "Formuliere eine Antwort auf diese Kundenmail:\\n\\n",
        "Strukturiere dieses Angebot als Newsletter:\\n\\n",
        "Erstelle eine Angebotsmail mit diesen Daten:\\n\\n",
    ]

    for starter in old_direct_starters:
        assert starter not in script

    assert "Bitte frage mich jetzt nach der Kundenmail" in script
    assert "Bitte frage mich jetzt nach dem Angebot" in script
    assert "Bitte frage mich jetzt nach Fahrzeug, Angebotsdaten" in script


def test_core_vinci_prompts_clarify_ambiguous_internal_requests_without_guessing():
    prompt_root = ROOT / "open-webui-prompts"
    for file_name in (
        "kahle-vinci-systemprompt.md",
        "kahle-vinci-thinking-systemprompt.md",
    ):
        prompt = (prompt_root / file_name).read_text(encoding="utf-8")

        assert "zwei oder mehr plausible Bedeutungen" in prompt, file_name
        assert "genau eine kurze Rueckfrage" in prompt, file_name
        assert "Nutzerabsicht nicht veraendern" in prompt, file_name
        assert "datenschutz@kahle.de" in prompt, file_name


def test_core_vinci_prompts_do_not_forward_marketing_opt_out_to_privacy():
    prompt_root = ROOT / "open-webui-prompts"
    for file_name in (
        "kahle-vinci-systemprompt.md",
        "kahle-vinci-thinking-systemprompt.md",
    ):
        prompt = (prompt_root / file_name).read_text(encoding="utf-8")

        assert "Datenschutz / Legal / Werbesperre" not in prompt, file_name
        assert "Werbewiderspruch" in prompt, file_name
        assert "besondere Merkmale" in prompt, file_name
        assert "Finanzdaten" in prompt, file_name


if __name__ == "__main__":
    test_all_vinci_prompts_handle_empty_starter_prompts()
    test_registered_suggestion_prompts_start_guided_input_flow()
    print("vinci starter prompt contract tests passed")
