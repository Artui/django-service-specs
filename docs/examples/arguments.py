"""Arguments and refusals: the shape check's tree, the closed set, and flat transports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.test import override_settings

# --8<-- [start:tree]
from django_service_specs import (
    InvalidArguments,
    Parameter,
    Parameters,
    UnknownArguments,
    check_arguments,
    coerce_flat,
)

BOOK = Parameters.of(
    Parameter("title", "string", required=True),
    Parameter("price", "string", format="decimal", required=True),
)
AUTHOR = Parameters.of(
    Parameter("name", "string", required=True),
    Parameter("books", "array", items=BOOK),
)


def refusal(arguments: dict[str, Any]) -> dict[Any, Any]:
    try:
        check_arguments(AUTHOR, arguments)
    except InvalidArguments as refused:
        return refused.detail
    return {}


ARGUMENTS = {
    "name": "Ursula",
    "books": [
        {"title": "The Dispossessed", "price": "9.99"},
        {"price": "a lot", "colour": "red"},
        "Always Coming Home",
    ],
}

REFUSED = {
    "books": {
        1: {
            "title": ["This field is required."],
            "price": ["Enter a number."],
            "colour": ["Unknown argument."],
        },
        2: {"non_field_errors": ["Expected an object."]},
    },
}
# --8<-- [end:tree]


# --8<-- [start:codes]
def codes(detail: Any) -> Any:
    """The tree with each message's code in its place, and ``"invalid"`` where it has none."""
    if isinstance(detail, Mapping):
        return {key: codes(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [codes(message) for message in detail]
    return getattr(detail, "code", "invalid")


CODES = {
    "books": {
        1: {"title": ["required"], "price": ["invalid"], "colour": ["unknown"]},
        2: {"non_field_errors": ["invalid"]},
    },
}
# --8<-- [end:codes]


# --8<-- [start:ignore]
def lenient(arguments: dict[str, Any]) -> dict[str, Any]:
    return check_arguments(AUTHOR, arguments, unknown_arguments=UnknownArguments.IGNORE)


SENT = {"name": "Ursula", "nickname": "UKL", "books": [{"title": "Lathe", "price": 7, "isbn": 1}]}
KEPT = {"name": "Ursula", "books": [{"title": "Lathe", "price": 7}]}
# --8<-- [end:ignore]


# --8<-- [start:flat]
FILTERS = Parameters.of(
    Parameter("limit", "integer"),
    Parameter("published", "boolean"),
    Parameter("ids", "array", items="integer"),
    Parameter("price_below", "string", format="decimal"),
)


def from_argv(raw: dict[str, Any]) -> dict[str, Any]:
    return check_arguments(FILTERS, coerce_flat(FILTERS, raw))


ARGV = {"limit": "10", "published": "true", "ids": "3", "price_below": "9.99"}
TYPED = {"limit": 10, "published": True, "ids": [3], "price_below": "9.99"}
# --8<-- [end:flat]


# --8<-- [start:length]
IDS = Parameters.of(Parameter("ids", "array", items="integer"))  # no max_length declared
PAGE = Parameters.of(Parameter("ids", "array", items="integer", min_length=1, max_length=50))

# check_arguments(IDS, {"ids": list(range(1001))}) refuses, at the list:
TOO_LONG = {"ids": ["Ensure this field has no more than 1000 elements."]}
# check_arguments(PAGE, {"ids": []}) refuses too:
TOO_SHORT = {"ids": ["Ensure this field has at least 1 elements."]}


def unbounded(arguments: dict[str, Any]) -> dict[str, Any]:
    with override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None):  # bounds no array
        return check_arguments(IDS, arguments)


# --8<-- [end:length]
