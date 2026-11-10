from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.utils import gettext_noop


class InvalidArguments(DispatchError):
    """The arguments were refused: their shape, or the Validator's verdict on them."""

    default_message: ClassVar[str] = gettext_noop("Invalid arguments.")

    def __init__(self, detail: Mapping[Any, Any], *, after_authorize: bool = False) -> None:
        super().__init__()
        self.detail: dict[Any, Any] = dict(detail)
        self.after_authorize: bool = after_authorize

    @property
    def missing(self) -> tuple[str, ...]:
        """The top-level arguments the call left out, sorted, those coded ``required``."""
        return tuple(
            sorted(
                name
                for name, messages in self.detail.items()
                if name != NON_FIELD_ERRORS
                and any(getattr(message, "code", None) == "required" for message in messages)
            )
        )
