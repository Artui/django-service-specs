"""A transport's answer to every outcome of one dispatch, in the two error families."""

from __future__ import annotations

# --8<-- [start:transport]
from typing import Any

from django_service_specs import (
    InvalidArguments,
    NotPermitted,
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
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
    except (NotPermitted, PrincipalUnavailable) as refused:
        return 403, {"detail": refused.message}
    # The operation refused. The subclasses first: each is also a ServiceError.
    except ServiceValidationError as refused:
        return 400, field_map(refused.detail)
    except ServiceNotFound as refused:
        return 404, {"detail": refused.message}
    except ServiceConflict as refused:
        return 409, {"detail": refused.message}
    except ServiceError as refused:
        return 422, {"detail": refused.message}
    if result.kind == "not_found":
        return 404, {"detail": "Not found."}
    return 200, present(spec, result)


def field_map(detail: Any) -> dict[str, Any]:
    """Every 400 body is a field map: a message about the input as a whole has its own key."""
    if isinstance(detail, dict):
        return detail
    return {"non_field_errors": detail if isinstance(detail, list) else [detail]}


# --8<-- [end:transport]
