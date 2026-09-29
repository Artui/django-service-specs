"""The helpers the HTTP transport's functions and views share."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser

from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.http.utils import answered_methods, request_principal
from tests.http.utils import FACTORY, note_spec, signed_in, titled_spec


class Principal:
    """A user object from a custom model with no ``is_active`` at all."""

    is_authenticated = True


class Deactivated:
    is_authenticated = True
    is_active = False


def test_a_principal_with_no_is_active_is_taken_as_active() -> None:
    # The default in ``getattr(user, "is_active", True)``: Django's own
    # ModelBackend reads a missing ``is_active`` the same way.
    principal = Principal()
    assert request_principal(signed_in(FACTORY.get("/"), principal)) is principal


def test_anonymous_is_the_principal_and_not_refused() -> None:
    assert isinstance(request_principal(signed_in(FACTORY.get("/"))), AnonymousUser)


def test_a_deactivated_principal_is_refused() -> None:
    with pytest.raises(PrincipalUnavailable):
        request_principal(signed_in(FACTORY.get("/"), Deactivated()))


@pytest.mark.parametrize(
    ("spec", "methods", "expected"),
    [
        (note_spec(), None, ("get", "head")),
        (titled_spec(), None, ("post",)),
        (titled_spec(), ("DELETE",), ("delete",)),
        (note_spec(), (), ()),
    ],
    ids=["selector", "service", "named", "none-named"],
)
def test_the_methods_a_spec_answers(spec: Any, methods: Any, expected: Any) -> None:
    assert answered_methods(spec, methods, label="SpecView") == expected
