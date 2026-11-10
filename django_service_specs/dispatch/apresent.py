from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


async def apresent(spec: ServiceSpec | SelectorSpec | SpecSource, result: DispatchResult) -> Any:
    """[`present`][django_service_specs.dispatch.present.present] in one executor hop."""
    return await sync_to_async(present, thread_sensitive=True)(spec, result)
