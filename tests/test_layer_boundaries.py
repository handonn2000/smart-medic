"""A layer may import from a layer BELOW it. Never from one above.

This rule is what lets several agents work in parallel without colliding, and it
is enforced here rather than described in a README because a rule that lives only
in documentation is violated by the third agent that reads it. A dependency cycle
between `extract/` and `decision/` is the surest way to lose the invariant that
only `decision/` applies a threshold.

    io < layout < extract < {assertion, linking} < decision < validate
    eval/  imports no layer at all — it reads JSON off disk
    src/   never imports scripts/ — that dependency runs one way

The walk is static (AST) and TRANSITIVE: importing a legal neighbour that itself
imports upwards is still a violation, and a static walk catches it even in a module
that cannot be imported yet.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "smart_medic"

#: Rank, low to high. Equal rank = may not import each other either.
LAYER_RANK = {
    "io": 0,
    "layout": 1,
    "extract": 2,
    "assertion": 3,
    "linking": 3,
    "decision": 4,
    "validate": 5,
}
#: L7. Outside the inference path; may import nothing from the layers.
MEASUREMENT_LAYERS = {"eval"}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _layer_of(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "smart_medic":
        return parts[1] if parts[1] in LAYER_RANK or parts[1] in MEASUREMENT_LAYERS else None
    return None


def _imports(path: Path) -> set[str]:
    """Direct `smart_medic.*` and `scripts.*` imports, relative ones resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rsplit(".", 1)[0]

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ("smart_medic", "scripts"):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                up = node.level - 1
                base = base[: len(base) - up] if up else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target.split(".")[0] in ("smart_medic", "scripts"):
                found.add(target)
                for alias in node.names:  # `from .x import y` may name a module
                    found.add(f"{target}.{alias.name}")
    return found


def _graph() -> tuple[dict[str, set[str]], set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    known: set[str] = set()
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _module_name(path)
        known.add(name)
        graph[name] |= _imports(path)
    return graph, known


def _reachable(start: str, graph: dict[str, set[str]], known: set[str]) -> set[str]:
    """Transitive closure over modules we actually have on disk."""
    seen: set[str] = set()
    stack = list(graph.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        # `from .x import name` may name an attribute, not a module — only follow
        # edges that correspond to a real file.
        if node in known:
            stack += list(graph.get(node, ()))
        else:
            parent = node.rsplit(".", 1)[0]
            if parent in known:
                stack += list(graph.get(parent, ()))
    return seen


def test_layers_only_import_downwards():
    graph, known = _graph()
    violations: list[str] = []

    for module in sorted(known):
        layer = _layer_of(module)
        if layer is None or layer not in LAYER_RANK:
            continue
        rank = LAYER_RANK[layer]
        for target in sorted(_reachable(module, graph, known)):
            tlayer = _layer_of(target)
            if tlayer is None:
                continue
            if tlayer in MEASUREMENT_LAYERS:
                violations.append(
                    f"{module} (L{rank} {layer}) reaches {target} — eval/ is L7, "
                    f"outside the inference path"
                )
                continue
            trank = LAYER_RANK[tlayer]
            if tlayer != layer and trank >= rank:
                violations.append(
                    f"{module} (L{rank} {layer}) reaches {target} (L{trank} {tlayer}) "
                    f"— a layer may only import DOWNWARDS"
                )

    assert not violations, (
        f"{len(violations)} layer-boundary violation(s):\n  "
        + "\n  ".join(sorted(set(violations))[:30])
    )


def test_eval_imports_no_layer():
    """`eval/` is the measurement. It reads JSON off disk and depends on no layer."""
    graph, known = _graph()
    violations = []
    for module in sorted(known):
        if _layer_of(module) not in MEASUREMENT_LAYERS:
            continue
        for target in sorted(_reachable(module, graph, known)):
            tlayer = _layer_of(target)
            if tlayer is not None and tlayer not in MEASUREMENT_LAYERS:
                violations.append(f"{module} imports {target} ({tlayer})")
    assert not violations, (
        "eval/ must not import any inference layer — it measures what is on disk:\n  "
        + "\n  ".join(violations)
    )


def test_src_never_imports_scripts():
    """`scripts/` reads `src/`, never the reverse. `scripts/` is where APIs live."""
    graph, _ = _graph()
    violations = [
        f"{module} imports {target}"
        for module, targets in graph.items()
        for target in sorted(targets)
        if target.split(".")[0] == "scripts"
    ]
    assert not violations, (
        "src/smart_medic/ must never import scripts/ — that is the build-time side, "
        "and it is the only place allowed to call a closed-source API (ADR 0003):\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize("layer", sorted(LAYER_RANK) + sorted(MEASUREMENT_LAYERS))
def test_every_layer_is_present(layer):
    """Guard the rank table: a renamed layer would silently stop being checked."""
    assert (PKG / layer).is_dir(), (
        f"LAYER_RANK/MEASUREMENT_LAYERS names {layer!r}, which is not a directory "
        f"under src/smart_medic/ — this test is silently skipping it"
    )
