#!/usr/bin/env python3
"""
Baut die installierbaren OpenWebUI-Tooldateien.

OpenWebUI nimmt pro Tool genau eine Datei entgegen und stellt keinen
Modulsuchpfad bereit. Die Hybrid-Retrieval-Tools teilen sich aber
`hybrid_retrieval.py` und `hybrid_retrieval_adapters.py`. Ohne diesen Schritt
verweisen sie auf Klassen, die zur Laufzeit nicht existieren.

Dieses Skript verkettet die geteilten Module mit dem jeweiligen Tool zu einer
eigenstaendigen Datei unter `dist/`. Die Quellen bleiben getrennt und testbar;
verteilt wird das Ergebnis.

Aufruf aus dem Repository-Wurzelverzeichnis:

    python stack/open-webui-tools/build_tools.py
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent

# Reihenfolge ist bedeutsam: Adapter benutzen RetrievalError aus hybrid_retrieval.
SHARED_MODULES = ("hybrid_retrieval.py", "hybrid_retrieval_adapters.py")
BUNDLES = {
    "rag_chat_hybrid_tool.py": SHARED_MODULES,
    "kahle_workflow_orchestrator.py": SHARED_MODULES,
}

GENERATED_NOTE = (
    "# Erzeugt von stack/open-webui-tools/build_tools.py. Nicht direkt bearbeiten.\n"
    "# Quellen: {sources}\n"
)


def split_source(path: Path) -> tuple[str | None, list[str], str]:
    """Zerlegt eine Datei in Docstring, Importzeilen und uebrigen Rumpf."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    docstring, body = None, list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        docstring = ast.get_source_segment(source, body[0])
        body = body[1:]

    imports, remainder = [], []
    for node in body:
        # lineno einer Klasse oder Funktion zeigt auf das Schluesselwort, nicht
        # auf ihre Dekoratoren. Ohne diese Korrektur verliert das Bundle jedes
        # @dataclass, und die Klasse nimmt zur Laufzeit keine Argumente mehr an.
        first = node.lineno
        for decorator in getattr(node, "decorator_list", []):
            first = min(first, decorator.lineno)
        segment = "".join(lines[first - 1:node.end_lineno])
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(segment.rstrip("\n"))
        else:
            remainder.append(segment)
    return docstring, imports, "".join(remainder)


def build(tool_name: str, shared: tuple[str, ...]) -> str:
    docstring, imports, tool_body = split_source(TOOLS_DIR / tool_name)

    shared_bodies, all_imports = [], list(imports)
    for module in shared:
        _, module_imports, module_body = split_source(TOOLS_DIR / module)
        all_imports = module_imports + all_imports
        shared_bodies.append(module_body)

    future, normal = [], []
    for line in all_imports:
        target = future if line.startswith("from __future__") else normal
        if line not in target:
            target.append(line)

    parts = []
    if docstring:
        parts.append(docstring + "\n")
    parts.append(GENERATED_NOTE.format(sources=", ".join(shared + (tool_name,))))
    parts.append("\n".join(future + sorted(normal)) + "\n\n\n")
    parts.append("\n\n".join(part.strip("\n") for part in shared_bodies) + "\n\n\n")
    parts.append(tool_body.strip("\n") + "\n")
    return "".join(parts)


def undefined_names(source: str) -> list[str]:
    """Namen, die der Bundle benutzt, aber nirgends bindet."""
    import builtins

    tree = ast.parse(source)
    bound = set(dir(builtins)) | {"self", "cls", "__name__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    used = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return sorted(used - bound)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Nur pruefen, ob dist/ dem aktuellen Quellstand entspricht")
    args = parser.parse_args()

    dist = TOOLS_DIR / "dist"
    dist.mkdir(exist_ok=True)
    failed = False

    for tool_name, shared in BUNDLES.items():
        bundle = build(tool_name, shared)
        missing = undefined_names(bundle)
        if missing:
            print(f"FEHLER {tool_name}: undefinierte Namen: {', '.join(missing)}")
            failed = True
            continue

        target = dist / tool_name
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if args.check:
            if current != bundle:
                print(f"VERALTET {target.relative_to(TOOLS_DIR.parents[1])}: neu bauen")
                failed = True
            else:
                print(f"aktuell  {target.name}")
            continue

        target.write_text(bundle, encoding="utf-8")
        print(f"gebaut   {target.name} ({len(bundle.splitlines())} Zeilen)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
