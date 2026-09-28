"""``InvalidArguments`` - the supplied arguments do not fit the declared parameters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from django_service_specs.dispatch.dispatch_error import DispatchError


class InvalidArguments(DispatchError):
    """The arguments were refused: their shape, or the Validator's verdict on them.

    Parameters are declared and arguments are supplied, and this refuses the
    arguments. It is raised by the shape check, the closed argument set,
    ``coerce_flat``, a Validator and the relation writes, so every refusal of
    input reaches a transport as one type.

    **Not a service validation error**, and not a subclass of one. A service
    raising
    [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
    is stating a business rule about well-shaped input; this says the input was
    not well-shaped, or did not validate. An MCP server answers the two
    differently on purpose.

    ``detail`` is a tree addressed by path, because nested arguments fail inside
    rows:

    - a field: ``{"title": ["..."]}``
    - a nested object: ``{"author": {"name": ["..."]}}``
    - rows, keyed by their ``int`` index, only the rows that failed:
      ``{"books": {1: {"title": ["..."]}}}``
    - a message about a row itself, under ``non_field_errors`` inside the row

    Every leaf is a list of ``str``, so the whole tree is JSON-serializable once
    the integer keys are written as strings, which is what ``json.dumps`` does.
    """

    default_message: ClassVar[str] = "Invalid arguments."

    def __init__(self, detail: Mapping[Any, Any]) -> None:
        super().__init__()
        self.detail: dict[Any, Any] = dict(detail)
