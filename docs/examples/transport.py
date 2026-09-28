"""A transport's answer to every outcome of one dispatch, in the two error families."""

from __future__ import annotations

# --8<-- [start:transport]
from typing import Any

from django_service_specs import (
    InvalidArguments,
    NotPermitted,
    ServiceConflict,
    ServiceError,
    ServiceSpec,
    ServiceValidationError,
    dispatch,
    present,
)


def answer(spec: ServiceSpec, principal: Any, arguments: dict[str, Any]) -> tuple[int, Any]:
    """One HTTP-shaped answer per outcome. Another transport maps the same types its own way."""
    try:
        result = dispatch(spec, principal=principal, arguments=arguments)
    # Dispatch refused, before the operation ran.
    except InvalidArguments as refused:
        return 400, refused.detail
    except NotPermitted as refused:
        return 403, {"detail": refused.message}
    # The operation refused. The subclasses first: each is also a ServiceError.
    except ServiceValidationError as refused:
        return 422, refused.detail
    except ServiceConflict as refused:
        return 409, {"detail": refused.message}
    except ServiceError as refused:
        return 400, {"detail": refused.message}
    if result.kind == "not_found":
        return 404, {"detail": "Not found."}
    return 200, present(spec, result)


# --8<-- [end:transport]
