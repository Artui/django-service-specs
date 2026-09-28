"""``apresent`` - ``present``, from async code."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


async def apresent(spec: ServiceSpec | SelectorSpec, result: DispatchResult) -> Any:
    """[`present`][django_service_specs.dispatch.present.present] in one executor hop.

    A presenter is sync-only and may query - reading a relation off a row the
    selector did not prefetch, or evaluating a list's queryset - and the kernel
    cannot tell in advance which, so the whole of ``present`` runs on Django's
    thread-sensitive executor rather than on the event loop. What comes back is
    plain data, safe to use on the loop.

    Raises:
        ValueError: ``kind="not_found"``, as ``present``.
    """
    return await sync_to_async(present, thread_sensitive=True)(spec, result)
