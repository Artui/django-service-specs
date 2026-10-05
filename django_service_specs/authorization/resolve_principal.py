"""``resolve_principal`` - an identifier off HTTP, to a principal that may act."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.utils import is_deactivated


def resolve_principal(identifier: Any) -> Any:
    """Look up the user who is to act, from an identifier a transport carries.

    HTTP has a session or a token to resolve a principal from; most transports
    this kernel dispatches for do not, so a caller hands the primary key it
    already has (a queue payload, a management command argument, an agent's own
    notion of who is asking) and this is the one place that becomes a user row.

    Every way an identifier can fail to name someone who may act becomes
    [`PrincipalUnavailable`][django_service_specs.authorization.principal_unavailable.PrincipalUnavailable],
    terminal and never a fallback:

    - no row with that primary key (``DoesNotExist``);
    - a malformed primary key (``ValueError``, ``TypeError``, or Django's own
      ``ValidationError`` - a non-UUID string against a UUID primary key raises
      that one instead of ``ValueError``);
    - the row is deactivated, by the rule dispatch applies to a principal it
      is handed (``is_active`` false, and a model with no such field reads as
      active). So ``adispatch(principal_id=...)`` refuses here, with the
      identifier in the message, and dispatch's own check never disagrees.

    Never ``AnonymousUser``: an operation dispatched with no resolvable
    principal has no principal, not an anonymous one.
    """
    user_model = get_user_model()
    try:
        user = user_model._default_manager.get(pk=identifier)
    except (user_model.DoesNotExist, ValueError, TypeError, ValidationError):
        raise PrincipalUnavailable(f"No principal with identifier {identifier!r}.") from None
    if is_deactivated(user):
        raise PrincipalUnavailable(f"The principal {identifier!r} is deactivated.")
    return user
