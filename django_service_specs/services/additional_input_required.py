from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.services.service_error import ServiceError


class AdditionalInputRequired(ServiceError):
    """A service cannot proceed without a value it was not given.

    Not "what you sent is wrong" - that is
    [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
    - but "I got far enough to discover I need something else", usually
    *conditional on what the service found*, so it cannot be expressed as a
    required parameter:

        def delete_rows(*, data, confirmed: bool = False):
            doomed = rows_matching(data)
            if len(doomed) > 100 and not confirmed:
                raise AdditionalInputRequired(
                    f"{len(doomed)} rows match. Confirm to proceed.",
                    schema={"confirmed": {"type": "boolean"}},
                )
            ...

    ``schema`` describes what is missing, keyed by the argument name the service
    expects it back under: a transport that can ask renders it, one that cannot
    still has a message worth showing. **The answer comes back as an ordinary
    argument** on every transport - an HTTP client re-submits with ``confirmed``
    in the body, an MCP client is asked and its answer is merged into the tool
    arguments before dispatch - so raising is the whole of the service's
    involvement; there is no callback to hold and no session to resume. The
    operation declares that argument like any other, so the closed argument set
    admits it on the second call.

    A [`ServiceError`][django_service_specs.services.service_error.ServiceError]
    subclass deliberately, so a transport that has never heard of it still
    reports that the operation could not be completed and why. One that wants to
    do better must catch it *before* its generic ``ServiceError`` handler.
    """

    def __init__(self, message: str, *, schema: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.schema: Mapping[str, Any] | None = schema
