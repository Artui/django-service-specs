"""``implements`` - an identity decorator stating which Protocol a callable conforms to."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F")


def implements(proto: type[F]) -> Callable[[F], F]:
    """Return the decorated callable unchanged, typed as conforming to ``proto``.

    ``proto`` is a parameterised service or selector Protocol:

        @implements(CreateService[NoteInput, Note])
        def create_note(*, data: NoteInput, **extras: Any) -> Note: ...

    A type checker reports a callable that does not conform - a keyword the
    Protocol passes and the callable does not take, a return of the wrong type -
    at the decorator line, as ty does.

    It lives in ``services/`` beside the service Protocols, and decorates a
    selector the same way, with
    [`ListSelector`][django_service_specs.selectors.list_selector.ListSelector]
    or [`RetrieveSelector`][django_service_specs.selectors.retrieve_selector.RetrieveSelector].
    Nothing changes at run time: dispatch binds a callable from the keywords it
    declares, annotated or not.
    """

    def _identity(fn: F) -> F:
        return fn

    return _identity
