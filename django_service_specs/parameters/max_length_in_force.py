from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameters import Parameter
from django_service_specs.settings import max_array_length


def max_length_in_force(param: Parameter) -> int | None:
    """The most elements the array ``param`` takes: its own ``max_length``, or the setting's."""
    if param.max_length is not None:
        return param.max_length
    default = max_array_length()
    if default is not None and param.min_length is not None and param.min_length > default:
        raise ImproperlyConfigured(
            f"Parameter {param.name!r}: min_length {param.min_length} is past the default maximum "
            f"{default} (SERVICE_SPECS_MAX_ARRAY_LENGTH), so no list could meet both; declare "
            "a max_length."
        )
    return default
