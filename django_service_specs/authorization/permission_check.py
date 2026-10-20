"""``PermissionCheck`` - the kernel's permission contract."""

from __future__ import annotations

import abc
from typing import Any


class PermissionCheck(abc.ABC):
    """Whether a principal may run a spec, and whether they may act on a row.

    A principal and a spec, and nothing else: no request and no view, because
    most transports have neither. Instances rather than classes, so a check can
    carry its own configuration (a codename, a group) and a spec reads as the
    list of checks it applies.

    ``has_permission`` is the class-level check, run before any row is resolved,
    so a principal refused here learns nothing about which rows exist.
    ``has_object_permission`` runs against the resolved target of a retrieve or
    an update; it allows by default, because most checks are class-level only.

    ``has_scope_permission`` is the same question for a call that resolves no
    single row: it is asked of the set a bulk call acts on or a collection
    reads, and of ``None`` where the call acts on no existing row (a create).
    It is a separate method rather than ``has_object_permission`` handed a set
    or ``None``, because a check written for a row would read an attribute off
    it and fail on neither; it allows by default for the same reason.

    **A method may ask for the call's arguments** by declaring a keyword
    ``arguments``: dispatch then hands it the call's shape-checked arguments,
    as a read-only mapping, at each of the three questions - a route's captured ``pk``, a
    filter the caller sent - and a method that does not declare it is asked
    without them. The base methods do not declare it, so every check
    written without it stays a valid override; a ``many`` call's rows are
    not among them, as they are validated after every check. Opt-in is by
    name, read layer by layer down the ``__wrapped__`` chain
    ``functools.wraps`` leaves: a layer spreading ``**kwargs`` passes the
    keyword to the one beneath, so it is handed only where a layer names it
    before any layer without ``**kwargs``, and a forwarding decorator keeps a
    check opted in. ``arguments`` is ``None`` where a transport calls
    ``authorize()`` without them, and a check that needs them decides for
    itself what that means; reading it as an allow fails open. Only the mapping
    is read-only: its values are the call's own objects, the ones the run
    receives, so a check must not mutate them.

    ``message`` is what [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    says when this check refuses; ``None`` keeps the generic wording.

    **Sync-only**, like every concept: a check may query, so the async path runs
    it in the executor. An ``async def`` method would answer with a coroutine,
    which is truthy and would allow every call, so a spec refuses a check
    declaring one when it is built, with ``ImproperlyConfigured`` naming the
    method; and an answer that is still to be awaited - from a plain ``def``
    wrapping an ``async def`` - is refused where it is read, failing closed.

    ``spec`` is typed ``Any`` in each method, and is always the ``ServiceSpec``
    or ``SelectorSpec`` being run. The spec modules import this one to declare
    their ``permissions`` field, so naming either class here would make the
    package that declares specs and the one that judges them import each
    other. A subclass may annotate it ``ServiceSpec | SelectorSpec``.
    """

    message: str | None = None

    @abc.abstractmethod
    def has_permission(self, principal: Any, spec: Any) -> bool:
        """Whether ``principal`` may run ``spec`` at all.

        ``spec`` is the ``ServiceSpec`` or ``SelectorSpec`` being run.
        """

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        """Whether ``principal`` may act on ``target``. Allows unless overridden.

        ``spec`` is the ``ServiceSpec`` or ``SelectorSpec`` being run.
        """
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        """Whether ``principal`` may act on ``scope``. Allows unless overridden.

        ``spec`` is the ``ServiceSpec`` or ``SelectorSpec`` being run.
        ``scope`` is the resolved set of a bulk or collection call, or ``None``
        for a call that acts on no existing row.
        """
        return True
