from __future__ import annotations

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.types.dispatch_error import DispatchError


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
