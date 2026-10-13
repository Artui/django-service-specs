from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

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
    assert (p.minimum, p.maximum) == (None, None)


def test_choices_are_normalized_to_a_tuple() -> None:
    assert Parameter("status", "string", choices=["a", "b"]).choices == ("a", "b")


@pytest.mark.parametrize("default", [[1, 2], {"sizes": [1]}, [], UNSET, None])
def test_a_parameter_is_hashable_whatever_its_default(default: Any) -> None:
    # A list default reaches a Parameter from the pydantic adapter, which
    # reports a field's default as given, and a transport caching a tool's
    # schema by its Parameters hashes every one, nested ones included.
    def declared() -> Parameter:
        return Parameter("sizes", "array", items="integer", default=copy.deepcopy(default))

    parameter, twin = declared(), declared()
    assert hash(parameter) == hash(twin)
    assert {parameter: "cached"}[twin] == "cached"
    assert hash(Parameter("box", "object", fields=Parameters.of(parameter))) == hash(
        Parameter("box", "object", fields=Parameters.of(twin))
    )
    # Reported as declared: not frozen into a tuple on the way in.
    assert parameter.default == default
    assert type(parameter.default) is type(default)


def test_a_default_still_tells_two_parameters_apart() -> None:
    # Out of the hash, not out of equality: two declarations differing only by
    # default share a hash and stay two keys.
    one, other = Parameter("n", "integer", default=[1]), Parameter("n", "integer", default=[2])
    assert hash(one) == hash(other)
    assert one != other
    assert len({one, other}) == 2


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


# --- a file -------------------------------------------------------------------------------


def test_a_file_is_a_parameter_type_and_an_element_type() -> None:
    # Not a JSON type: only a multipart body or a Python caller carries one,
    # and the output side, which shares the JSON types, never returns one.
    assert Parameter("notes", "file").type == "file"
    assert Parameter("notes", "array", items="file").items == "file"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": "file", "choices": ("a.txt",)},
        {"type": "array", "items": "file", "choices": ("a.txt",)},
    ],
    ids=["file", "array-of-files"],
)
def test_a_file_has_no_choices(kwargs: dict) -> None:
    # A file is compared by identity, so no declared value could ever match.
    with pytest.raises(ImproperlyConfigured, match="a file is never one of a list of values"):
        Parameter("notes", **kwargs)


# --- bounds ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bound",
    [True, Decimal("1"), "1", float("inf"), float("nan")],
    ids=["bool", "decimal", "string", "infinity", "nan"],
)
@pytest.mark.parametrize("side", ["minimum", "maximum"])
def test_a_bound_must_be_a_finite_number(side: str, bound: Any) -> None:
    # The schema states it as a JSON number, which none of these is.
    with pytest.raises(ImproperlyConfigured, match=f"{side} .* is not a finite int or float"):
        Parameter("price", "number", **{side: bound})


def test_a_large_int_bound_is_taken_without_reading_it_as_a_float() -> None:
    # ``math.isfinite`` would overflow on it.
    assert Parameter("n", "integer", maximum=10**400).maximum == 10**400


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": "string"},
        {"type": "string", "format": "date"},
        {"type": "boolean"},
        {"type": "array", "items": "number"},
        {"type": "object"},
        {"type": "file"},
    ],
    ids=["string", "date", "boolean", "array", "object", "file"],
)
def test_a_bound_describes_a_number(kwargs: dict[str, Any]) -> None:
    with pytest.raises(
        ImproperlyConfigured, match="a bound describes a number or a decimal string"
    ):
        Parameter("price", maximum=1, **kwargs)


def test_a_decimal_string_takes_a_bound() -> None:
    p = Parameter("price", "string", format="decimal", minimum=-1e50, maximum=1e50)
    assert (p.minimum, p.maximum) == (-1e50, 1e50)


def test_a_minimum_past_the_maximum_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="minimum 2 is past maximum 1"):
        Parameter("n", "integer", minimum=2, maximum=1)


def test_one_bound_may_equal_the_other() -> None:
    assert Parameter("n", "integer", minimum=1, maximum=1.0).maximum == 1.0


# --- choice labels ----------------------------------------------------------------------------


def test_choice_labels_are_none_unless_declared() -> None:
    assert Parameter("status", "string", choices=("a",)).choice_labels is None


@pytest.mark.parametrize(
    "labels",
    [{"draft": "Draft", "live": "Published"}, [("draft", "Draft"), ("live", "Published")]],
    ids=["mapping", "pairs"],
)
def test_choice_labels_are_normalized_to_pairs(labels: Any) -> None:
    # A mapping is how a reader writes it and a list of pairs is how Django
    # spells ``choices``, so both are read, and stored as a tuple of pairs so
    # the declaration stays hashable.
    status = Parameter("status", "string", choices=("draft", "live"), choice_labels=labels)
    assert status.choice_labels == (("draft", "Draft"), ("live", "Published"))
    twin = Parameter("status", "string", choices=("draft", "live"), choice_labels=labels)
    assert hash(status) == hash(twin)
    assert status != Parameter("status", "string", choices=("draft", "live"))


def test_a_choice_may_go_unlabelled() -> None:
    status = Parameter("status", "string", choices=("draft", "live"), choice_labels={"live": "On"})
    assert status.choice_labels == (("live", "On"),)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"choice_labels": {"draft": "Draft"}}, "choice_labels name declared choices"),
        (
            {"choices": ("draft",), "choice_labels": {"live": "Published"}},
            r"choice_labels label \['live'\], which choices do not list",
        ),
    ],
)
def test_a_label_for_no_declared_choice_is_refused(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message) as caught:
        Parameter("status", "string", **kwargs)
    assert "Parameter 'status'" in str(caught.value)
