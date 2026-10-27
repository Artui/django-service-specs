from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser

from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, Record, Titled
from tests.parameters.utils import coded

REQUIRED = "This field is required."


def test_carries_a_copy_of_the_detail_tree() -> None:
    detail = {"books": {1: {"title": ["taken"]}}}
    error = InvalidArguments(detail)
    assert error.detail == detail
    detail["other"] = ["x"]
    assert "other" not in error.detail
    assert error.message == InvalidArguments.default_message


def test_is_a_dispatch_error_and_not_a_service_error() -> None:
    assert issubclass(InvalidArguments, DispatchError)
    assert [c.__name__ for c in InvalidArguments.__mro__] == [
        "InvalidArguments",
        "DispatchError",
        "Exception",
        "BaseException",
        "object",
    ]


# --- missing -----------------------------------------------------------------------------

_REQUIRED = CodedMessage("This field is required.", "required")
_NOT_A_NUMBER = CodedMessage("A valid integer is required.", "invalid")


def _shape_refusal(parameters: Parameters, arguments: dict[str, Any]) -> InvalidArguments:
    with pytest.raises(InvalidArguments) as caught:
        check_arguments(parameters, arguments)
    return caught.value


def test_missing_names_the_top_level_arguments_the_shape_check_found_absent() -> None:
    parameters = Parameters.of(
        Parameter("title", "string", required=True), Parameter("pages", "integer")
    )

    assert _shape_refusal(parameters, {}).missing == ("title",)


def test_missing_leaves_out_an_argument_that_is_present_but_wrong() -> None:
    parameters = Parameters.of(
        Parameter("title", "string", required=True),
        Parameter("pages", "integer", required=True),
    )

    refused = _shape_refusal(parameters, {"pages": "many"})

    assert set(refused.detail) == {"title", "pages"}
    assert refused.missing == ("title",)


def test_missing_is_sorted_whatever_order_the_parameters_are_declared_in() -> None:
    parameters = Parameters.of(
        Parameter("b", "string", required=True),
        Parameter("c", "string", required=True),
        Parameter("a", "string", required=True),
    )

    refused = _shape_refusal(parameters, {})

    assert list(refused.detail) == ["b", "c", "a"]
    assert refused.missing == ("a", "b", "c")


def test_missing_is_empty_when_nothing_was_absent() -> None:
    assert _shape_refusal(Parameters.of(Parameter("n", "integer")), {"n": "x"}).missing == ()
    assert InvalidArguments({}).missing == ()


def test_missing_does_not_reach_into_a_nested_object_or_a_row() -> None:
    publisher = Parameters.of(Parameter("name", "string", required=True))
    book = Parameters.of(
        Parameter("title", "string", required=True),
        Parameter("publisher", "object", fields=publisher),
    )
    parameters = Parameters.of(Parameter("books", "array", items=book))

    in_a_row = _shape_refusal(parameters, {"books": [{"publisher": {"name": "x"}}]})
    in_a_nested_object = _shape_refusal(parameters, {"books": [{"title": "t", "publisher": {}}]})

    assert in_a_row.detail == {"books": {0: {"title": [REQUIRED]}}}
    assert in_a_nested_object.detail == {"books": {0: {"publisher": {"name": [REQUIRED]}}}}
    assert in_a_row.missing == in_a_nested_object.missing == ()


def test_missing_leaves_out_a_many_call_s_row_field() -> None:
    # Held by name: the top-level argument ``items`` is present, only a row's
    # ``title`` is not, and the row's field is no argument of the call.
    spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Titled())

    with pytest.raises(InvalidArguments) as caught:
        check_call(spec, principal=AnonymousUser(), arguments={"items": [{"title": 3}, {}]})

    assert caught.value.detail["items"][1] == {"title": [REQUIRED]}
    assert caught.value.missing == ()


def test_missing_reads_the_code_and_not_the_words() -> None:
    # A Validator's own message is a plain ``str``, and another mistake's code
    # is no absence, whatever the words say.
    refused = InvalidArguments(
        {
            "plain": ["This field is required."],
            "wrong": [_NOT_A_NUMBER],
            "both": [_NOT_A_NUMBER, _REQUIRED],
            "absent": [_REQUIRED],
        }
    )

    assert refused.missing == ("absent", "both")


def test_missing_is_not_the_node_s_own_message() -> None:
    # ``non_field_errors`` is a message about the whole call, not an argument.
    assert InvalidArguments({NON_FIELD_ERRORS: [_REQUIRED]}).missing == ()


def test_missing_names_what_a_selector_refused_for_a_read_nothing_filled() -> None:
    selector = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, tenant, region: [],
        reads=Parameters.of(Parameter("tenant", "string"), Parameter("region", "string")),
        permissions=OPEN,
    )

    with pytest.raises(InvalidArguments) as caught:
        dispatch(selector, principal=AnonymousUser(), arguments={"region": "eu"})

    assert coded(caught.value.detail) == {"tenant": [("This field is required.", "required")]}
    assert caught.value.missing == ("tenant",)


def test_missing_is_read_only() -> None:
    refused = InvalidArguments({"a": [_REQUIRED]})

    with pytest.raises(AttributeError):
        refused.missing = ()  # type: ignore[misc]


# --- after_authorize ---------------------------------------------------------------------


def test_a_refusal_is_not_marked_as_raised_after_authorization_unless_it_says_so() -> None:
    assert InvalidArguments({"a": ["x"]}).after_authorize is False
    assert InvalidArguments({"a": ["x"]}, after_authorize=True).after_authorize is True


def test_after_authorize_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        InvalidArguments({"a": ["x"]}, True)  # type: ignore[misc]
