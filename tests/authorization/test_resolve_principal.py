from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

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
