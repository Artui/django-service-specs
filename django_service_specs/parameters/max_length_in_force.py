from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameters import Parameter
from django_service_specs.settings import max_array_length


def max_length_in_force(param: Parameter) -> int | None:
    """The most elements the array ``param`` takes: its own ``max_length``, or the setting's.

    One reading for every place that bounds or describes a list - the shape
    check, ``coerce_flat``, the split of a flat value, a ``many`` call's rows
    and the schema, and a transport reading a list itself - so the bound a
    client is told is the bound it meets.
    ``None`` where the setting is ``None`` and nothing is declared.

    Raises:
        ImproperlyConfigured: a ``min_length`` past the setting's maximum on a
            parameter that declares no maximum of its own, which no call could
            meet: at the call, and when the parameter's schema is built, so a
            transport listing every schema fails on it too. Found here because
            the setting is read only then, so the declaration cannot be
            refused where it is written.
    """
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
