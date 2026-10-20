from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.output import Output, OutputField

ID = OutputField("id", "integer")
NAME = OutputField("name", "string")


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
    assert f.items_nullable is False


def test_choices_are_value_and_display_pairs() -> None:
    f = OutputField("status", "string", choices=[["d", "Draft"], ("p", "Published")])
    assert f.choices == (("d", "Draft"), ("p", "Published"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "str"}, "is not a JSON type"),
        ({"type": "string", "format": "email"}, "format 'email' is not one of"),
        # A schema states the format beside the type, so one on a number would
        # publish a decimal no JSON number is.
        ({"type": "number", "format": "decimal"}, "a format describes a string"),
        ({"type": "string", "fields": Output()}, "fields describes an object"),
        ({"type": "string", "items": "string"}, "items describes an array"),
        ({"type": "array", "items_nullable": True}, "items_nullable describes a declared element"),
        ({"type": "string", "choices": ["d", "p"]}, "choices are \\(value, display\\) pairs"),
        # As on Parameter: a list of values says what type they are.
        ({"type": "any", "choices": [("d", "Draft")]}, "an untyped value is matched by no list"),
        # As on Parameter: one spelling for an element of any type.
        ({"type": "array", "items": "any"}, "an array with no items takes any element"),
        ({"type": "any", "format": "date"}, "a format describes a string"),
    ],
)
def test_refuses_a_declaration_no_reader_can_act_on(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        OutputField("x", **kwargs)


def test_nesting_is_legal_where_the_type_allows_it() -> None:
    inner = Output((OutputField("name", "string"),))
    assert OutputField("author", "object", fields=inner).fields is inner
    assert OutputField("books", "array", items=inner).items is inner


def test_any_declares_a_value_whose_json_type_is_open() -> None:
    """A computed field or a JSON column holds whatever its producer returns,
    so the declaration must be able to say so rather than claim a string."""
    f = OutputField("extra", "any", nullable=True, label="Extra")
    assert (f.type, f.nullable, f.label) == ("any", True, "Extra")


# Output shares the formats with Parameter, so an identifier field is a string
# in the ``uuid`` format, which output_schema states beside its type.
@pytest.mark.parametrize("fmt", ["decimal", "uuid"])
def test_a_format_on_a_string_is_kept(fmt: str) -> None:
    assert OutputField("x", "string", format=fmt).format == fmt


def test_uuid_choices_are_held_in_their_canonical_spelling() -> None:
    # The spelling ``str()`` gives a model's UUID: held by
    # test_a_uuid_choice_is_spoken_for_the_spelling_a_model_presents.
    canonical = "0b8a3c1e-5d2f-4e6a-9b7c-1d2e3f4a5b6c"
    field = OutputField(
        "project", "string", format="uuid", choices=[("{" + canonical.upper() + "}", "Ada")]
    )
    assert field.choices == ((canonical, "Ada"),)


def test_two_spellings_of_one_uuid_leave_one_choice_with_the_first_display() -> None:
    canonical = "0b8a3c1e-5d2f-4e6a-9b7c-1d2e3f4a5b6c"
    other = "9f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b"
    choices = [(canonical.upper(), "First"), (other, "Other"), ("{" + canonical + "}", "Second")]
    field = OutputField("project", "string", format="uuid", choices=choices)
    assert field.choices == ((canonical, "First"), (other, "Other"))


def test_repeated_choices_nothing_canonicalised_are_kept() -> None:
    field = OutputField("status", "string", choices=[("a", "A"), ("a", "B")])
    assert field.choices == (("a", "A"), ("a", "B"))


def test_an_arrays_declared_element_may_be_nullable() -> None:
    inner = Output((OutputField("name", "string"),))
    assert OutputField("scores", "array", items="integer", items_nullable=True).items_nullable
    assert OutputField("books", "array", items=inner, items_nullable=True).items_nullable


def test_is_ordered_by_declaration() -> None:
    out = Output([NAME, ID])
    assert out.fields == (NAME, ID)
    assert out.names() == ("name", "id")
    assert list(out) == [NAME, ID]
    assert len(out) == 2
    assert out.get("id") is ID
    assert out.get("missing") is None


def test_a_name_declared_twice_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"\['id'\] more than once"):
        Output((ID, OutputField("id", "string")))
