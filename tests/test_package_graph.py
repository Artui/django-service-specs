"""The subpackages import one another in a line, never in a ring, and no import is guarded.

A ring of packages is the shape rule 8 describes: the first leaf loaded from
any of them runs a package ``__init__`` that imports the rest, and one of those
imports the leaf back, half-initialized. It also leaves no order the packages
can be read in. So the graph of every import in the package, annotation-only
ones included, is held acyclic here.

An ``if TYPE_CHECKING:`` guard is how a ring is hidden from the interpreter
while the type checker still sees it, so none may exist in the package at all.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import django_service_specs

ROOT = Path(django_service_specs.__file__).parent


def _package_of(dotted: str) -> str | None:
    parts = dotted.split(".")
    if parts[0] != "django_service_specs" or len(parts) < 3:
        return None
    if parts[1] == "adapters" and len(parts) >= 4:
        return f"adapters.{parts[2]}"
    return parts[1]


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (
            ".".join(path.relative_to(ROOT.parent).with_suffix("").parts),
            ast.parse(path.read_text()),
        )
        for path in ROOT.rglob("*.py")
    ]


def _graph() -> dict[str, set[str]]:
    edges: dict[str, set[str]] = defaultdict(set)
    for module, tree in _modules():
        source = _package_of(module)
        if source is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = _package_of(node.module)
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


def _guards(tree: ast.AST) -> list[int]:
    """The lines naming ``TYPE_CHECKING`` as a name or an attribute (``typing.TYPE_CHECKING``)."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING")
        or (isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING")
        or (
            isinstance(node, ast.alias) and node.name == "TYPE_CHECKING" and hasattr(node, "lineno")
        )
    ]


def test_the_imports_form_no_ring() -> None:
    assert _rings(_graph()) == []


def test_the_ring_finder_finds_a_ring() -> None:
    # The negative control: a finder that returned nothing for every graph
    # would pass the test above for a package that was all rings.
    assert _rings({"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}) == [["a", "b", "c"]]
    assert _rings({"a": {"b"}, "b": {"c"}}) == []


def test_no_module_guards_an_import_with_type_checking() -> None:
    assert {module: lines for module, tree in _modules() if (lines := _guards(tree))} == {}


def test_the_guard_finder_finds_each_spelling() -> None:
    for source in (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\n",
        "import typing\nif typing.TYPE_CHECKING:\n    pass\n",
    ):
        assert _guards(ast.parse(source)) != []
    assert _guards(ast.parse("x = 1\n")) == []
