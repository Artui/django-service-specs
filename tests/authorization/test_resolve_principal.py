from __future__ import annotations

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal

User = get_user_model()


@pytest.mark.django_db
def test_missing_identifier_raises() -> None:
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal(999999)


@pytest.mark.django_db
def test_malformed_identifier_raises() -> None:
    # A non-integer string against an integer primary key raises ValueError
    # from the field's own coercion, not DoesNotExist; both become the same
    # refusal, because the caller cannot act on either outcome differently.
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal("abc")


@pytest.mark.django_db
def test_an_identifier_of_the_wrong_kind_raises() -> None:
    # A list reaches the integer field's own coercion as ``int([])``, which is a
    # TypeError rather than a ValueError - a queue payload that decoded a
    # structure where it expected a key.
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal([1])


@pytest.mark.django_db
def test_a_malformed_key_the_field_refuses_as_a_validation_error_raises() -> None:
    # A UUID primary key refuses a malformed string with Django's own
    # ValidationError, not ValueError. The suite's user model has an integer
    # key, so the lookup is made to raise what a UUID key would.
    refusal = ValidationError("not a valid UUID")
    with (
        mock.patch.object(User._default_manager, "get", side_effect=refusal),
        pytest.raises(PrincipalUnavailable, match="No principal"),
    ):
        resolve_principal("not-a-uuid")


def test_an_unrelated_failure_is_not_read_as_a_missing_principal() -> None:
    # Only the refusals that mean "no such principal" are translated; a
    # database outage says nothing about the identifier and must surface as
    # itself rather than as a principal the caller should stop asking for.
    with (
        mock.patch.object(User._default_manager, "get", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError, match="down"),
    ):
        resolve_principal(1)


@pytest.mark.django_db
def test_none_identifier_raises() -> None:
    with pytest.raises(PrincipalUnavailable, match="No principal"):
        resolve_principal(None)


@pytest.mark.django_db
def test_inactive_user_raises() -> None:
    user = User.objects.create(username="dormant", is_active=False)
    with pytest.raises(PrincipalUnavailable, match="deactivated"):
        resolve_principal(user.pk)


@pytest.mark.django_db
def test_active_user_is_returned() -> None:
    user = User.objects.create(username="active", is_active=True)
    assert resolve_principal(user.pk) == user
