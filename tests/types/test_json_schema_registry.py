from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from django_service_specs.schema.registered_fragment import registered_fragment
from django_service_specs.types.json_schema_registry import JsonSchemaRegistry


class Base: ...


class Middle(Base): ...


class Leaf(Middle): ...


def _answer(registry: JsonSchemaRegistry, field_type: type) -> object:
    return registered_fragment(field_type, registry, project_registry=False)


def test_an_empty_registry_answers_nothing() -> None:
    assert _answer(JsonSchemaRegistry(), Leaf) is None


def test_a_rule_answers_its_own_class_and_its_subclasses() -> None:
    registry = JsonSchemaRegistry(fields=((Middle, {"type": "string"}),))
    assert _answer(registry, Middle) == {"type": "string"}
    assert _answer(registry, Leaf) == {"type": "string"}
    assert _answer(registry, Base) is None


def test_the_most_specific_class_wins_whatever_the_order_of_the_rules() -> None:
    # Listed base first, so a first-isinstance-match reading would answer the base's rule.
    registry = JsonSchemaRegistry(
        fields=((Base, {"type": "integer"}), (Middle, {"type": "string"}))
    )
    assert _answer(registry, Leaf) == {"type": "string"}
    assert _answer(registry, Base) == {"type": "integer"}


def test_a_rule_an_extension_prepends_wins_over_the_registry_s_own_for_one_class() -> None:
    base = JsonSchemaRegistry(fields=((Middle, {"type": "integer"}),))
    extended = base.extend(fields=[(Middle, {"type": "string"})])
    assert _answer(extended, Middle) == {"type": "string"}
    assert _answer(base, Middle) == {"type": "integer"}


def test_extending_with_nothing_is_an_equal_registry() -> None:
    registry = JsonSchemaRegistry(fields=((Middle, {"type": "string"}),))
    assert registry.extend() == registry


def test_a_registry_is_immutable() -> None:
    with pytest.raises(AttributeError):
        JsonSchemaRegistry().fields = ()


def _imported(module: str) -> set[str]:
    """Every name ``module``'s source imports, a ``from`` import's names joined to its module."""
    tree = ast.parse(Path(str(importlib.import_module(module).__file__)).read_text())
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.add(node.module)
            named.update(f"{node.module}.{alias.name}" for alias in node.names)
    return named


def _forms_or_drf(names: set[str]) -> list[str]:
    return sorted(name for name in names if name.startswith(("rest_framework", "django.forms")))


@pytest.mark.parametrize(
    "module",
    [
        "django_service_specs.types.json_schema_registry",
        "django_service_specs.schema.registered_fragment",
        "django_service_specs.settings",
        "django_service_specs.specs.route_captures",
        "django_service_specs.schema.fragment_keywords",
    ],
)
def test_the_rules_and_their_resolver_import_neither_forms_nor_drf(module: str) -> None:
    assert _forms_or_drf(_imported(module)) == []


def test_the_import_check_sees_a_forms_import() -> None:
    # The negative control: the forms adapter's ``from django import forms`` is caught.
    forms_adapter = "django_service_specs.adapters.forms.form_validator"
    assert "django.forms" in _forms_or_drf(_imported(forms_adapter))
