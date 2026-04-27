from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
TARGETS = [
    REPO_ROOT / "modules" / "semantic_purity.py",
    REPO_ROOT / "modules" / "markdown_exporter.py",
    REPO_ROOT / "modules" / "content_brief_builder.py",
    REPO_ROOT / "modules" / "context_builder.py",
    REPO_ROOT / "modules" / "koray_analyzer.py",
]


def find_duplicate_top_level_defs(path: Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    seen: dict[str, list[int]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            seen[node.name].append(node.lineno)
    return {name: lines for name, lines in seen.items() if len(lines) > 1}


def test_target_modules_have_no_duplicate_top_level_defs() -> None:
    failures = {
        str(path.relative_to(REPO_ROOT)): duplicates
        for path in TARGETS
        if (duplicates := find_duplicate_top_level_defs(path))
    }
    assert not failures, f"Duplicate top-level defs found: {failures}"
