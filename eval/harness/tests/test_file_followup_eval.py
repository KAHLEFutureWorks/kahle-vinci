from file_followup_eval import BLOCK_MARKER, score_turn, summarize_runs


def _message(tools=(), outputs=(), content=""):
    output = [{"type": "function_call", "name": name} for name in tools]
    output += [{"type": "function_call_output", "output": text} for text in outputs]
    return {"content": content, "output": output}


def test_score_turn_counts_blocked_calls_and_finds_the_requested_file():
    message = _message(
        tools=["kahle_workflow_execute", "kahle_workflow_execute", "file_to_md_save"],
        outputs=[BLOCK_MARKER + ": nicht ausgeführt", BLOCK_MARKER + ": nicht ausgeführt",
                 '{"download_url": "http://x/files/d/abc", "filename": "ergebnis.md"}'],
        content="Hier ist die Datei: [ergebnis.md](http://x/files/d/abc)",
    )

    row = score_turn(message, expected_extension=".md", wall_ms=4200)

    assert row == {
        "tools": ["file_to_md_save", "kahle_workflow_execute"],
        "tool_calls": 3,
        "blocked_calls": 2,
        "file_delivered": True,
        "wall_ms": 4200,
    }


def test_score_turn_without_link_or_with_wrong_type_is_not_delivered():
    no_link = score_turn(_message(content="Erledigt."), expected_extension=".md", wall_ms=1)
    wrong = score_turn(
        _message(content="[ergebnis.pdf](http://x/files/d/abc)"), expected_extension=".md", wall_ms=1,
    )

    assert no_link["file_delivered"] is False and no_link["tool_calls"] == 0
    assert wrong["file_delivered"] is False


def test_summary_reports_rates_and_blocked_call_distribution_per_model():
    rows = [
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 4, "blocked_calls": 3, "file_delivered": True, "wall_ms": 9000},
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 1, "blocked_calls": 0, "file_delivered": True, "wall_ms": 3000},
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 0, "blocked_calls": 0, "file_delivered": False, "wall_ms": 2000},
        {"model": "m", "turn": 2, "tools": [], "tool_calls": 1, "blocked_calls": 0, "file_delivered": True, "wall_ms": 5000},
        {"model": "m", "turn": 3, "error": "HTTPError"},
    ]

    summary = summarize_runs(rows)["m"]

    assert summary["turn2_delivered"] == "1/1"
    assert summary["turn3_delivered"] == "2/3"
    assert summary["turn3_blocked_max"] == 3
    assert summary["turn3_blocked_p50"] == 0
    assert summary["turn3_with_blocked"] == 1
    assert summary["turn3_wall_p50_ms"] == 3000
    assert summary["errors"] == 1
