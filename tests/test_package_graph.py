"""The subpackages import one another in a line, never in a ring.

A ring of packages is the shape rule 8 describes: the first leaf loaded from
any of them runs a package ``__init__`` that imports the rest, and one of those
imports the leaf back, half-initialized. It also leaves no order the packages
can be read in. So the graph of imports that run is held acyclic here.

An import under ``if TYPE_CHECKING:`` runs nothing, so it is not an edge of
that graph. It is still a dependency a reader has to know, which is why the
packages that annotate each other are one named set below and not left
implicit. The set is empty: no package names another's types without
importing it.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import django_service_specs

ROOT = Path(django_service_specs.__file__).parent

# Annotation-only edges: (importing package, imported package). Each is an
# import that exists to type a signature whose module the other package
# already imports at run time. None is left: a check is handed the spec it
# judges typed ``Any``, since a spec declares its checks.
ANNOTATION_ONLY: set[tuple[str, str]] = set()


def _package_of(dotted: str) -> str | None:
    parts = dotted.split(".")
    if parts[0] != "django_service_specs" or len(parts) < 3:
        return None
    if parts[1] == "adapters" and len(parts) >= 4:
        return f"adapters.{parts[2]}"
    return parts[1]


def _type_checking_body(node: ast.AST) -> list[ast.stmt] | None:
    """The statements under ``if TYPE_CHECKING:``, or ``None`` if ``node`` is no such block."""
    if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
        return node.body
    return None


def _imports(node: ast.AST, *, annotation_only: bool) -> list[str]:
    """The ``from django_service_specs...`` modules under ``node``, in or out of ``TYPE_CHECKING``."""
    found: list[str] = []
    for child in ast.iter_child_nodes(node):
        guarded = _type_checking_body(child)
        if guarded is not None:
            if annotation_only:
                for inner in guarded:
                    found.extend(_all_imports(inner))
            continue
        if isinstance(child, ast.ImportFrom) and child.module:
            if not annotation_only:
                found.append(child.module)
        else:
            found.extend(_imports(child, annotation_only=annotation_only))
    return found


def _all_imports(node: ast.AST) -> list[str]:
    return [
        n.module for n in ast.walk(node) if isinstance(n, ast.ImportFrom) and n.module is not None
    ]


def _graph(*, annotation_only: bool) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = defaultdict(set)
    for path in ROOT.rglob("*.py"):
        module = ".".join(path.relative_to(ROOT.parent).with_suffix("").parts)
        source = _package_of(module)
        if source is None:
            continue
        for imported in _imports(ast.parse(path.read_text()), annotation_only=annotation_only):
            target = _package_of(imported)
            if target is not None and target != source:
                edges[source].add(target)
    return edges


def _rings(edges: dict[str, set[str]]) -> list[list[str]]:
    """The groups of packages that import one another, round and round (Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    rings: list[list[str]] = []

    def visit(package: str) -> None:
        index[package] = low[package] = len(index)
        stack.append(package)
        on_stack.add(package)
        for other in sorted(edges.get(package, ())):
            if other not in index:
                visit(other)
                low[package] = min(low[package], low[other])
            elif other in on_stack:
                low[package] = min(low[package], index[other])
        if low[package] == index[package]:
            ring = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                ring.append(member)
                if member == package:
                    break
            if len(ring) > 1:
                rings.append(sorted(ring))

    for package in sorted(edges):
        if package not in index:
            visit(package)
    return rings


def test_the_imports_that_run_form_no_ring() -> None:
    assert _rings(_graph(annotation_only=False)) == []


def test_the_packages_that_annotate_each_other_are_the_named_ones() -> None:
    running = _graph(annotation_only=False)
    only = {
        (source, target)
        for source, targets in _graph(annotation_only=True).items()
        for target in targets
        if target not in running.get(source, set())
    }
    assert only == ANNOTATION_ONLY
