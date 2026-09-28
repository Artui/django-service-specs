"""``UnknownArguments`` - what happens to an argument no parameter declares."""

from __future__ import annotations

from enum import Enum


class UnknownArguments(str, Enum):
    """The closed argument set's policy, applied at every level of nesting.

    ``REJECT`` is the default everywhere. An untrusted caller's undeclared key
    is refused before it costs a query, and a trusted one's typo - a command's
    misspelt option, a task enqueued with last month's argument name - fails
    where the caller can see it rather than being dropped on the floor.

    There is no pass-through. An undeclared argument reaching a callable is
    exactly what the closed set exists to prevent: on a selector, with no
    Validator in front of it, it would let a caller supply a keyword the
    operation's author never offered.
    """

    REJECT = "reject"
    """Refuse the undeclared key with ``InvalidArguments``, at the level it appeared."""

    IGNORE = "ignore"
    """Drop the undeclared key and carry on."""
