from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.utils import checked_server_values
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.server_arguments import ServerArguments


def apply_server_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    arguments: Mapping[str, Any],
    server: ServerArguments,
    *,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``arguments`` with the server values added under ``server``, in a new dict."""
    names = server.names()
    applied = {key: value for key, value in arguments.items() if key not in names}
    if server.values:
        spec = kernel_spec(spec)
        applied.update(
            checked_server_values(spec, spec.parameters(call_context=call_context), server.values)
        )
    return applied
