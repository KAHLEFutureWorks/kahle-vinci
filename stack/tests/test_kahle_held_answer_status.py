"""A held knowledge answer shows a running status (UI acceptance 09.10.).

In enforce mode the answer text stays hidden until it is validated. Without a
status the chat looked frozen for several seconds. The status starts as soon
as the answer is held and is always closed before the final message.
"""

from pathlib import Path

MIDDLEWARE = Path(__file__).resolve().parents[1] / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def test_held_answer_status_opens_when_the_answer_is_held_and_closes_at_the_end():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    opens = [index for index in range(len(source)) if source.startswith("await _open_held_answer_status()", index)]
    close = source.index("await _close_held_answer_status()")
    final = source.index("                data = {\n                    'done': True,\n                    'output': output,")

    # Once at stream start, once when a knowledge tool switches holding on mid-stream.
    assert len(opens) == 2
    assert all(index < close for index in opens)
    assert close < final
    assert "'description': 'Antwort wird erstellt und anhand der Quellen geprüft'" in source
