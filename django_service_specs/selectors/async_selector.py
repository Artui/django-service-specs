"""``AsyncSelector`` - the structural type of any ``async def`` selector."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AsyncSelector(Protocol):
    """The ``async def`` sibling of [`Selector`][django_service_specs.selectors.selector.Selector].

    A ``SelectorSpec``'s ``selector`` may be ``async def``, and
    [`adispatch`][django_service_specs.dispatch.adispatch.adispatch] awaits it.
    To a type checker the two Protocols differ in the return, an awaitable
    here. An ``isinstance`` check cannot tell them apart, since both ask only
    whether the object is callable;
    [`is_async`][django_service_specs.services.is_async.is_async] is the run-time
    question.
    """

    async def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
