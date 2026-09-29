from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.types.unset import UNSET

ROW = Parameters.of(Parameter("title", "string", required=True))


def test_defaults() -> None:
    p = Parameter("pk", "integer")
    assert (p.required, p.format, p.items, p.fields, p.choices, p.nullable, p.help) == (
        False,
        None,
        None,
        None,
        None,
        False,
        None,
    )
    assert p.default is UNSET
    assert p.items_nullable is False


def test_choices_are_normalized_to_a_tuple() -> None:
    assert Parameter("status", "string", choices=["a", "b"]).choices == ("a", "b")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "str"}, "is not a JSON type"),
        ({"type": "string", "format": "uuid"}, "format 'uuid' is not one of"),
        ({"type": "integer", "format": "decimal"}, "a format describes a string"),
        ({"type": "string", "items": "string"}, "items describes an array's element"),
        ({"type": "array", "items": "str"}, "items 'str' is not a JSON type"),
        ({"type": "array", "fields": ROW}, "fields describes an object's own parameters"),
        # An undeclared element admits anything, null included, so saying so
        # again describes nothing a reader could act on.
        ({"type": "array", "items_nullable": True}, "items_nullable describes a declared element"),
    ],
)
def test_refuses_a_declaration_no_reader_can_act_on(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message) as caught:
        Parameter("x", **kwargs)
    assert "Parameter 'x'" in str(caught.value)


def test_nested_is_an_objects_fields_or_an_arrays_rows() -> None:
    assert Parameter("author", "object", fields=ROW).nested is ROW
    assert Parameter("books", "array", items=ROW).nested is ROW
    assert Parameter("tags", "array", items="string").nested is None
    assert Parameter("tags", "array").nested is None
    assert Parameter("title", "string").nested is None


def test_a_format_on_a_string_is_kept() -> None:
    assert Parameter("price", "string", format="decimal").format == "decimal"


def test_an_arrays_declared_element_may_be_nullable() -> None:
    assert Parameter("scores", "array", items="integer", items_nullable=True).items_nullable
    assert Parameter("books", "array", items=ROW, items_nullable=True).items_nullable
