from __future__ import annotations

import math
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "identifier",
    [
        pytest.param(999999, id="missing"),
        # A non-integer string raises ValueError from the field's own coercion, not DoesNotExist.
        pytest.param("abc", id="malformed"),
        pytest.param([1], id="wrong-kind"),
        pytest.param(None, id="none"),
    ],
)
def test_an_identifier_naming_no_row_raises(identifier: object) -> None:
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal(identifier)


@pytest.mark.django_db
@pytest.mark.usefixtures("unstated_ranges")
@pytest.mark.parametrize("identifier", [2**63, -(2**63) - 1, str(2**63)])
def test_an_identifier_past_the_key_s_column_raises(identifier: object) -> None:
    # It names no row.
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal(identifier)


@pytest.mark.django_db
def test_a_malformed_key_the_field_refuses_as_a_validation_error_raises() -> None:
    # A UUID primary key refuses a malformed string with Django's own ValidationError.
    refusal = ValidationError("not a valid UUID")
    with (
        mock.patch.object(User._default_manager, "get", side_effect=refusal),
        pytest.raises(PrincipalUnavailable, match="No principal"),
    ):
        resolve_principal("1")


def test_an_unrelated_failure_is_not_read_as_a_missing_principal() -> None:
    # Only the refusals that mean "no such principal" are translated.
    with (
        mock.patch.object(User._default_manager, "get", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError, match="down"),
    ):
        resolve_principal(1)


@pytest.mark.parametrize("identifier", [math.inf, -math.inf], ids=["above", "below"])
def test_an_infinite_identifier_is_no_principal(identifier: float) -> None:
    # The integer key's lookup reads it through ``int``, which raised OverflowError for an infinity.
    with pytest.raises(PrincipalUnavailable, match="No principal with identifier"):
        resolve_principal(identifier)


@pytest.mark.django_db
def test_inactive_user_raises() -> None:
    user = User.objects.create(username="dormant", is_active=False)
    with pytest.raises(PrincipalUnavailable, match="deactivated"):
        resolve_principal(user.pk)


@pytest.mark.django_db
def test_active_user_is_returned() -> None:
    user = User.objects.create(username="active", is_active=True)
    assert resolve_principal(user.pk) == user
