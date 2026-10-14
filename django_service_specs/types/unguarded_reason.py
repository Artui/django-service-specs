"""``UnguardedReason`` - why a registered spec authorizes nothing."""

from __future__ import annotations

from enum import Enum


class UnguardedReason(str, Enum):
    """The declaration that leaves a spec open to every principal.

    Read from ``authorize``: every check in ``spec.permissions`` must pass, in
    order, so one real check beside an ``Unrestricted()`` guards the spec, and
    a spec authorizes nothing only when **every** check it declares is
    ``Unrestricted``. That is ``UNRESTRICTED``, a decision somebody wrote down.

    No other declaration reaches a registry unguarded. ``permissions=None`` is
    refused when the spec is registered, and an empty ``permissions`` - which
    every check would pass vacuously - is refused when the spec is built, so
    there is no member for either.

    Inheriting from ``str`` keeps the value JSON-serializable while still
    behaving as a proper enum for ``is`` / ``==``.
    """

    UNRESTRICTED = "unrestricted"
