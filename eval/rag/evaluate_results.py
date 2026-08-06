#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def load_questions(path: Path) -> dict[tuple[str, str], dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    return {(kb, item["question"]): item for kb, items in payload.get("knowledgebases", {}).items() for item in items}


def score(questions_path: Path, results_path: Path) -> dict:
    expected = load_questions(questions_path)
    records = [json.loads(line) for line in results_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    scored = []
    for record in records:
        definition = expected.get((record.get("knowledgebase"), record.get("question")), {})
        answer = str(record.get("answer") or "")
        sources = record.get("sources") or []
        serialized_sources = json.dumps(sources, ensure_ascii=False).casefold()
        patterns = [str(value).casefold() for value in definition.get("expected_sources", [])]
        must_terms = [str(value).casefold() for value in definition.get("must_have_terms", [])]
        expect_no_answer = bool(definition.get("expect_no_answer"))
        no_answer = "keine verlässliche freigegebene information" in answer.casefold() or "information in den quellen fehlt" in answer.casefold()
        document_hit = (all(pattern in serialized_sources for pattern in patterns) if patterns else bool(sources))
        if expect_no_answer:
            document_hit = no_answer and not sources
        source_links = [str(source.get("source_url") or source.get("url") or "") for source in sources if isinstance(source, dict)]
        linked = expect_no_answer or bool(source_links and all(link.startswith("/wissen/api/portal/sources/") for link in source_links))
        term_hit = expect_no_answer or not must_terms or all(term in answer.casefold() for term in must_terms)
        scored.append({"question": record.get("question"), "document_hit": document_hit,
                       "source_link_ok": linked, "term_hit": term_hit, "expect_no_answer": expect_no_answer})
    count = len(scored) or 1
    return {
        "questions": len(scored),
        "document_hit_rate": sum(item["document_hit"] for item in scored) / count,
        "source_link_rate": sum(item["source_link_ok"] for item in scored) / count,
        "term_hit_rate": sum(item["term_hit"] for item in scored) / count,
        "details": scored,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--questions", type=Path, default=Path("eval/rag/questions.yml"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = score(args.questions, args.results)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(output, encoding="utf-8")
    print(output)
    return 0 if report["questions"] and report["document_hit_rate"] >= .90 and report["source_link_rate"] >= .95 else 1


if __name__ == "__main__":
    sys.exit(main())
