from __future__ import annotations

import copy
import inspect
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.types.unset import UNSET

ROW = Parameters.of(Parameter("title", "string", required=True))


def test_only_the_name_and_the_type_are_positional() -> None:
    # Every other field is keyword-only, so a field added among them shifts no
    # call written positionally, and their order is not part of the contract.
    kinds = {name: param.kind for name, param in inspect.signature(Parameter).parameters.items()}
    positional = [
        name for name, kind in kinds.items() if kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert positional == ["name", "type"]
    assert Parameter.__match_args__ == ("name", "type")
    with pytest.raises(TypeError):
        Parameter("pk", "integer", True)


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
        {"type": "object"},
        {"type": "file"},
    ],
    ids=["string", "date", "boolean", "object", "file"],
)
def test_a_bound_describes_a_number(kwargs: dict[str, Any]) -> None:
    with pytest.raises(
        ImproperlyConfigured, match="a bound describes a number or a decimal string"
    ):
        Parameter("price", maximum=1, **kwargs)


def test_a_decimal_string_takes_a_bound() -> None:
    p = Parameter("price", "string", format="decimal", minimum=-1e50, maximum=1e50)
    assert (p.minimum, p.maximum) == (-1e50, 1e50)


# --- an array's element: its format and its bounds ------------------------------------------


def test_a_decimal_array_reads_each_element_as_a_bounded_decimal() -> None:
    # A django-filter CSV number filter: each element is the decimal its
    # string spells, bounded as a scalar number filter is.
    p = Parameter("pks", "array", items="string", format="decimal", minimum=-1e50, maximum=1e50)
    assert (p.items, p.format, p.minimum, p.maximum) == ("string", "decimal", -1e50, 1e50)


@pytest.mark.parametrize("items", ["integer", "number"])
def test_a_bound_on_an_array_of_numbers_bounds_each_element(items: str) -> None:
    # Beside a length, which counts the list: the two pairs say different things.
    p = Parameter("ids", "array", items=items, minimum=1, maximum=10, max_length=3)
    assert (p.minimum, p.maximum, p.max_length) == (1, 10, 3)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "a format on an array describes each element, which must be a string"),
        (
            {"items": "number"},
            "a format on an array describes each element, which must be a string",
        ),
        ({"items": ROW}, "a format on an array describes each element, which must be a string"),
        (
            {"items": "string", "format": "date"},
            "an array's element takes no format but 'decimal'",
        ),
        (
            {"items": "string", "format": "date-time"},
            "an array's element takes no format but 'decimal'",
        ),
    ],
    ids=["no-items", "number", "rows", "date", "date-time"],
)
def test_an_array_s_format_is_a_decimal_string_element_s_alone(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        Parameter("pks", "array", **{"format": "decimal", **kwargs})


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"items": "string"}, {"items": "boolean"}, {"items": ROW}, {"items": "file"}],
    ids=["no-items", "string", "boolean", "rows", "file"],
)
@pytest.mark.parametrize("side", ["minimum", "maximum"])
def test_a_bound_on_an_array_describes_a_numeric_element(kwargs: dict[str, Any], side: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="a bound on an array describes each element"):
        Parameter("pks", "array", **{side: 1, **kwargs})


def test_a_minimum_past_the_maximum_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="minimum 2 is past maximum 1"):
        Parameter("n", "integer", minimum=2, maximum=1)


def test_one_bound_may_equal_the_other() -> None:
    assert Parameter("n", "integer", minimum=1, maximum=1.0).maximum == 1.0


# --- array lengths -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "length",
    [True, 1.0, "1", -1],
    ids=["bool", "float", "string", "negative"],
)
@pytest.mark.parametrize("side", ["min_length", "max_length"])
def test_a_length_must_be_a_non_negative_int(side: str, length: Any) -> None:
    # A count of elements: ``bool`` is an ``int`` to Python and no count.
    with pytest.raises(ImproperlyConfigured, match=f"{side} .* is not a non-negative int"):
        Parameter("ids", "array", **{side: length})


@pytest.mark.parametrize("side", ["min_length", "max_length"])
def test_a_length_describes_an_array(side: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="a length describes an array; this parameter"):
        Parameter("title", "string", **{side: 1})


@pytest.mark.parametrize("side", ["min_length", "max_length"])
def test_a_length_may_stand_alone_and_be_zero(side: str) -> None:
    # Zero is a count, so a falsy check in place of ``is not None`` would
    # refuse it as no length or take it as none.
    param = Parameter("ids", "array", **{side: 0})
    assert getattr(param, side) == 0


def test_one_length_may_equal_the_other_and_not_pass_it() -> None:
    assert Parameter("ids", "array", min_length=2, max_length=2).max_length == 2
    with pytest.raises(ImproperlyConfigured, match="min_length 3 is past max_length 2"):
        Parameter("ids", "array", min_length=3, max_length=2)


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


# --- any ---------------------------------------------------------------------------------------


def test_any_is_a_parameter_type() -> None:
    # What an unannotated read declares: ``lambda pk: ...`` takes 3 and "abc" alike.
    p = Parameter("pk", "any", required=True, nullable=True, help="A key.", default=None)

    assert (p.type, p.required, p.nullable, p.default) == ("any", True, True, None)


def test_any_has_no_choices() -> None:
    with pytest.raises(ImproperlyConfigured, match="an untyped value is matched by no list"):
        Parameter("pk", "any", choices=[1, "a"])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"format": "date"}, "a format describes a string; this parameter is 'any'"),
        ({"minimum": 1}, "a bound describes a number or a decimal string; this parameter is 'any'"),
        ({"items": "string"}, "items describes an array's element"),
        ({"fields": ROW}, "fields describes an object's own parameters"),
    ],
    ids=["format", "bound", "items", "fields"],
)
def test_any_carries_nothing_a_type_would_describe(kwargs: dict, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        Parameter("pk", "any", **kwargs)


def test_an_array_does_not_declare_any_as_its_element() -> None:
    # An array with no ``items`` takes any element already: one spelling for it.
    with pytest.raises(ImproperlyConfigured, match="takes any element already; declare no items"):
        Parameter("ids", "array", items="any")
