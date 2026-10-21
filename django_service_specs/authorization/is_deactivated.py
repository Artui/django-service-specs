"""``is_deactivated`` - the one rule for a principal that may not act at all."""

from __future__ import annotations

from typing import Any


def is_deactivated(principal: Any) -> bool:
    """True for an authenticated principal whose ``is_active`` is false.

    ``ModelBackend`` never logs a deactivated account in, but
    ``AllowAllUsersModelBackend`` and a project's own backend may, and a
    transport that holds a user object of its own may hand one over long after
    it was deactivated. The kernel's rule is that a deactivated principal never
    acts, whichever way it arrived.

    The kernel reads the rule in two places: dispatch, refusing the principal
    it was handed, first and whether or not a ``Grant`` came with it; and
    ``resolve_principal``, refusing the row an identifier named. It is public
    so that a transport in a distribution of its own refuses exactly the
    principals dispatch refuses, by calling this rather than restating it, as
    django-spec-html's entry points do with ``request.user`` before the
    request is read.
    It imports nothing that imports dispatch, so each reader can read it
    without a cycle.

    Both attributes are read with ``getattr`` rather than assumed, because a
    principal is whatever a transport hands over:

    - **No ``is_active`` reads as active**, as ``ModelBackend`` reads it: a
      custom user model is not required to declare the field.
    - **Anonymous is not deactivated.** ``AnonymousUser.is_active`` is false,
      so the rule asks about authenticated principals alone, and anonymous goes
      on to the permission check, which is what decides whether anonymous may
      act. A principal with no ``is_authenticated`` is not anonymous, so it is
      read as authenticated and refused only when it says it is inactive.

    Each condition is held by its own test in
    ``tests/authorization/test_is_deactivated.py``:
    ``test_anonymous_is_not_deactivated`` fails without the first and
    ``test_an_active_user_is_not_deactivated`` without the second.
    """
    return bool(getattr(principal, "is_authenticated", True)) and not getattr(
        principal, "is_active", True
    )
