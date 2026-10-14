"""``Selector`` - the structural type of any synchronous selector."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Selector(Protocol):
    """Any callable returning a queryset, a list or one object.

    The loosest description of a ``SelectorSpec``'s ``selector``: dispatch binds
    it from the keywords it declares, drawn from the keyword pool and the reads
    the spec declares, so no signature is imposed and conforming is optional.
    For a typed result, use
    [`ListSelector`][django_service_specs.selectors.list_selector.ListSelector]
    or [`RetrieveSelector`][django_service_specs.selectors.retrieve_selector.RetrieveSelector].

    Runtime-checkable, and an ``isinstance`` check asks only whether the object
    is callable: an ``async def`` passes it too, so it cannot tell the two
    kinds apart.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
