from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django_service_specs.authorization.is_deactivated import is_deactivated
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.parameters.utils import key_past_its_column


def resolve_principal(identifier: Any) -> Any:
    """Look up the user who is to act, from an identifier a transport carries."""
    user_model = get_user_model()
    manager = user_model._default_manager
    try:
        if key_past_its_column(manager.all(), "pk", identifier):
            raise user_model.DoesNotExist
        user = manager.get(pk=identifier)
    except (user_model.DoesNotExist, ValueError, TypeError, ValidationError):
        raise PrincipalUnavailable(f"No principal with identifier {identifier!r}.") from None
    if is_deactivated(user):
        raise PrincipalUnavailable(f"The principal {identifier!r} is deactivated.")
    return user
