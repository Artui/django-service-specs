from __future__ import annotations

from typing import ClassVar

from django.utils.translation import gettext

from django_service_specs.types.utils import gettext_noop


class DispatchError(Exception):
    """A refusal made by dispatch rather than by the operation."""

    default_message: ClassVar[str] = gettext_noop("The operation could not be dispatched.")

    def __init__(self, message: str | None = None) -> None:
        self.message = message if message is not None else gettext(self.default_message)
        super().__init__(self.message)
