from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.utils import KERNEL_ROW_ERRORS, ROW_ERROR_READERS

ErrorT = TypeVar("ErrorT", bound=Exception)


def register_row_error(error_class: type[ErrorT], read_detail: Callable[[ErrorT], Any]) -> None:
    """Re-root ``error_class`` under the row that raised it, as the kernel's own refusals are."""
    if not isinstance(error_class, type) or not issubclass(error_class, Exception):
        raise ImproperlyConfigured(
            f"register_row_error: {error_class!r} is not an exception class. Register "
            "the class a row service raises, with the function that reads its detail."
        )
    overlapping = [
        handled.__name__
        for handled in KERNEL_ROW_ERRORS
        if issubclass(error_class, handled) or issubclass(handled, error_class)
    ]
    if overlapping:
        raise ImproperlyConfigured(
            f"register_row_error: {error_class.__name__} overlaps "
            f"{', '.join(overlapping)}, which a relation write already re-roots under "
            "the row by its own rule. Register a class beside those, not one of them "
            "or one covering them."
        )
    current = ROW_ERROR_READERS.get(error_class)
    if current is not None and current is not read_detail:
        raise ImproperlyConfigured(
            f"register_row_error: {error_class.__name__} is already registered with "
            f"{current!r}. A class has one reader, so the second registration is "
            "refused rather than replacing the first."
        )
    ROW_ERROR_READERS[error_class] = read_detail
