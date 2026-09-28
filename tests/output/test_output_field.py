from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField


def test_defaults() -> None:
    f = OutputField("id", "integer")
    assert (f.format, f.nullable, f.label, f.choices, f.marking, f.fields, f.items) == (
        None,
        False,
        None,
        None,
        None,
        None,
        None,
    )
    assert f.always_present is True


def test_choices_are_value_and_display_pairs() -> None:
    f = OutputField("status", "string", choices=[["d", "Draft"], ("p", "Published")])
    assert f.choices == (("d", "Draft"), ("p", "Published"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "str"}, "is not a JSON type"),
        ({"type": "string", "format": "uuid"}, "format 'uuid' is not one of"),
        ({"type": "string", "fields": Output()}, "fields describes an object"),
        ({"type": "string", "items": "string"}, "items describes an array"),
        ({"type": "string", "choices": ["d", "p"]}, "choices are \\(value, display\\) pairs"),
    ],
)
def test_refuses_a_declaration_no_reader_can_act_on(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        OutputField("x", **kwargs)


def test_nesting_is_legal_where_the_type_allows_it() -> None:
    inner = Output((OutputField("name", "string"),))
    assert OutputField("author", "object", fields=inner).fields is inner
    assert OutputField("books", "array", items=inner).items is inner
