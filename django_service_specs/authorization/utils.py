"""Helpers shared by everything that decides whether a principal may act at all.

The deactivated rule is read in three places: dispatch, refusing the principal
it was handed; ``resolve_principal``, refusing the row an identifier named; and
the HTTP entry points, refusing ``request.user`` before the request is read.
It is written once here so the three cannot disagree about who is refused.
Nothing here imports anything that imports dispatch, so each of the three can
read it without a cycle.
"""

from __future__ import annotations

from typing import Any


def is_deactivated(principal: Any) -> bool:
    """True for an authenticated principal whose ``is_active`` is false.

    ``ModelBackend`` never logs a deactivated account in, but
    ``AllowAllUsersModelBackend`` and a project's own backend may, and a
    transport that holds a user object of its own may hand one over long after
    it was deactivated. The kernel's rule is that a deactivated principal never
    acts, whichever way it arrived.

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
    ``tests/authorization/test_utils.py``:
    ``test_anonymous_is_not_deactivated`` fails without the first and
    ``test_an_active_user_is_not_deactivated`` without the second.
    """
    return bool(getattr(principal, "is_authenticated", True)) and not getattr(
        principal, "is_active", True
    )
