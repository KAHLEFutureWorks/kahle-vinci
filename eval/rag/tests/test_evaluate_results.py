import json
from pathlib import Path

from evaluate_results import score


def test_eval_scores_document_hits_secure_source_links_and_no_answer(tmp_path: Path):
    questions = tmp_path / "questions.yml"
    questions.write_text("""knowledgebases:
  service:
    - question: "Was gilt?"
      expected_sources: ["doc-1"]
      must_have_terms: ["A1b"]
    - question: "Was ist unbekannt?"
      expect_no_answer: true
""", encoding="utf-8")
    results = tmp_path / "results.jsonl"
    rows = [
        {"knowledgebase":"service","question":"Was gilt?","answer":"A1b gilt.",
         "sources":[{"document_id":"doc-1","source_url":"/wissen/api/portal/sources/v1"}]},
        {"knowledgebase":"service","question":"Was ist unbekannt?",
         "answer":"Dazu habe ich keine verlässliche freigegebene Information.","sources":[]},
    ]
    results.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    report = score(questions, results)
    assert report["document_hit_rate"] == 1
    assert report["source_link_rate"] == 1
