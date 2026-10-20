"""Three-turn file conversation per model: knowledge answer, PDF from the result,
convert that PDF to Markdown. Counts tools, blocked calls, delivery and time only;
no question or answer text leaves this module.

Specialized Verification: needs a running local stack, IONOS models and
OPENWEBUI_API_KEY (JWT session token).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_eval import answer_text, nearest_rank
from runtime_harness_eval import HarnessRuntimeClient, model_tool_ids

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rag"))
from run_runtime_eval import ConversationState  # noqa: E402

QUESTION = "Wer ist für die Garantieabwicklung zuständig?"
TURN2 = "Erstelle mir aus dem Ergebnis eine PDF"
TURN3 = "Wandle die eben erstellte PDF in eine Markdown-Datei um"

BLOCK_MARKER = "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT"
_FILE_LINK = re.compile(
    r"\[([^\]]+)\]\((?:https?://[^)\s]+)?/files/(?:d/[A-Za-z0-9_-]+|download\?token=[^)\s]+)\)"
)
_FILE_NAME_LINE = re.compile(r"(?im)^\s*Datei:\s*(\S+)\s*$")


def score_turn(message: dict[str, Any], *, expected_extension: str, wall_ms: int) -> dict[str, Any]:
    output = [item for item in message.get("output") or () if isinstance(item, dict)]
    calls = [str(item.get("name") or "") for item in output if item.get("type") == "function_call"]
    results = [str(item.get("output") or "") for item in output if item.get("type") == "function_call_output"]
    text = answer_text(message)
    links = _FILE_LINK.findall(text)
    # The guard writes "[Datei herunterladen](link)" and the name on a "Datei:" line.
    names = [*links, *_FILE_NAME_LINE.findall(text)] if links else []
    delivered = any(name.strip().lower().endswith(expected_extension) for name in names)
    return {
        "tools": sorted(set(calls)),
        "tool_calls": len(calls),
        "blocked_calls": sum(BLOCK_MARKER in result for result in results),
        "file_delivered": delivered,
        "wall_ms": wall_ms,
    }


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for model in sorted({str(row["model"]) for row in rows}):
        items = [row for row in rows if row["model"] == model]
        ok = [row for row in items if "error" not in row]
        turn2 = [row for row in ok if row["turn"] == 2]
        turn3 = [row for row in ok if row["turn"] == 3]
        blocked = [row["blocked_calls"] for row in turn3]
        summary[model] = {
            "turn2_delivered": f"{sum(row['file_delivered'] for row in turn2)}/{len(turn2)}",
            "turn3_delivered": f"{sum(row['file_delivered'] for row in turn3)}/{len(turn3)}",
            "turn3_blocked_p50": nearest_rank(blocked, 0.5),
            "turn3_blocked_max": max(blocked) if blocked else None,
            "turn3_with_blocked": sum(value > 0 for value in blocked),
            "turn3_wall_p50_ms": nearest_rank([row["wall_ms"] for row in turn3], 0.5),
            "errors": len(items) - len(ok),
        }
    return summary


def _follow_up(client, chat_id: str, parent_id: str, messages: list[dict[str, str]], tool_ids: list[str]) -> dict:
    """Continue the stored chat; the workflow tool reads the previous result from it."""
    user_id, assistant_id = str(uuid4()), str(uuid4())
    body = {
        "model": client.model, "id": assistant_id, "parent_id": parent_id, "chat_id": chat_id,
        "session_id": str(uuid4()),
        "user_message": {"id": user_id, "parentId": parent_id, "childrenIds": [assistant_id],
                         "role": "user", "content": messages[-1]["content"], "timestamp": int(time.time())},
        "messages": messages, "tool_ids": list(tool_ids), "stream": True,
        "stream_options": {"include_usage": True},
    }
    message, _ = client._start_and_wait(body, assistant_id, ConversationState(chat_id, parent_id))
    return message


def run_conversation(client, tool_ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    first, chat_id = client.ask_messages([{"role": "user", "content": QUESTION}], tool_ids)
    history = [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": answer_text(first)}]
    try:
        parent = first["id"]
        for turn, prompt, extension in ((2, TURN2, ".pdf"), (3, TURN3, ".md")):
            history.append({"role": "user", "content": prompt})
            started = time.monotonic()
            message = _follow_up(client, chat_id, parent, history, tool_ids)
            wall_ms = round((time.monotonic() - started) * 1000)
            rows.append({"model": client.model, "turn": turn,
                         **score_turn(message, expected_extension=extension, wall_ms=wall_ms)})
            history.append({"role": "assistant", "content": answer_text(message)})
            parent = message["id"]
    finally:
        try:
            client.delete_chat(chat_id)
        except Exception:
            pass
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3004")
    parser.add_argument("--models", default="kahle-vinci-thinking,vinci-2-clone-clone-clone,kahle-vinci-max-thinking")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/harness/results"))
    parser.add_argument("--api-key-env", default="OPENWEBUI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"{args.api_key_env} fehlt")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rows: list[dict[str, Any]] = []
    for model in [item.strip() for item in args.models.split(",") if item.strip()]:
        client = HarnessRuntimeClient(args.base_url, api_key, model, args.timeout, 1.0)
        tool_ids = model_tool_ids(client.model_info())
        for _ in range(args.repeat):
            try:
                rows.extend(run_conversation(client, tool_ids))
            except Exception as error:  # one failed conversation must not stop the matrix
                rows.append({"model": model, "turn": 3, "error": type(error).__name__})
    (args.output_dir / f"file-followup-{stamp}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    summary = summarize_runs(rows)
    (args.output_dir / f"file-followup-{stamp}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
