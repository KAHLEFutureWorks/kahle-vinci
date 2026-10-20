"""Three-turn file conversation per model: knowledge answer, PDF from the result,
convert that PDF to Markdown. Counts tools, blocked calls, delivery and time only;
no question or answer text leaves this module.

Specialized Verification: needs a running local stack, IONOS models and
OPENWEBUI_API_KEY (JWT session token).
"""

from __future__ import annotations

import re
from typing import Any

from harness_eval import answer_text, nearest_rank

BLOCK_MARKER = "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT"
_FILE_LINK = re.compile(
    r"\[([^\]]+)\]\((?:https?://[^)\s]+)?/files/(?:d/[A-Za-z0-9_-]+|download\?token=[^)\s]+)\)"
)


def score_turn(message: dict[str, Any], *, expected_extension: str, wall_ms: int) -> dict[str, Any]:
    output = [item for item in message.get("output") or () if isinstance(item, dict)]
    calls = [str(item.get("name") or "") for item in output if item.get("type") == "function_call"]
    results = [str(item.get("output") or "") for item in output if item.get("type") == "function_call_output"]
    delivered = any(
        name.strip().lower().endswith(expected_extension)
        for name in _FILE_LINK.findall(answer_text(message))
    )
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
