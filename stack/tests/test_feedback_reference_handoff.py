import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "open-webui-tools" / "rag_chat_hybrid_tool.py"


def load_feedback_link_helper():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_feedback_link"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {}
    exec(compile(module, str(TOOL), "exec"), namespace)
    return namespace["_feedback_link"]


class FeedbackReferenceHandoffTest(unittest.TestCase):
    def test_feedback_link_uses_the_stable_portal_reference_contract(self):
        helper = load_feedback_link_helper()
        link = helper("chat-1", "message-1")
        self.assertEqual(
            link,
            "[Wissensfehler melden](/wissen/?feedback=1&chat_id=chat-1&message_id=message-1)",
        )
        self.assertNotIn("document_ids", link)


if __name__ == "__main__":
    unittest.main()
