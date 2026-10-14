from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.mutations.utils import KERNEL_ROW_ERRORS, ROW_ERROR_READERS

ErrorT = TypeVar("ErrorT", bound=Exception)


def register_row_error(error_class: type[ErrorT], read_detail: Callable[[ErrorT], Any]) -> None:
    """Re-root ``error_class`` under the row that raised it, as the kernel's own refusals are.

    A relation write re-addresses a refusal raised inside one row - by a row
    service, or by the write of a row further down - under that row's place in
    the arguments, so the caller learns which row was refused.
    It does that for the two refusals this package raises and for Django's own
    write failures. A refusal from a library this package cannot name - a
    framework's validation error, raised by a row service written for that
    framework - would otherwise escape naming no row. Registering its class
    puts it in the same tree:

    - ``read_detail`` is handed the exception and returns its detail: a mapping
      of field names to messages, or the row's own messages as a list or a
      string. It is placed at the row's address as the kernel's refusals are -
      a collection's row under its ``int`` index, a list or string under
      ``non_field_errors`` inside the row - and the messages are kept as they
      are, codes and all.
    - The re-rooted tree is handed to ``error_class`` as its one argument, and
      that is what is raised. The class is kept because the class says who
      refused and decides how each transport answers. A subclass raised by a
      row is caught as the registered class and rebuilt as it, so register the
      narrowest class whose constructor takes a detail this way.

    A grandchild's refusal is re-rooted at each row it passes, so it arrives
    carrying both addresses. A list form - a list as long as the incoming one,
    empty against the rows that passed - is a rendering of this tree, and the
    transport answering in it renders it.

    Registering the same class with the same reader again does nothing, so a
    registration that runs at import or in an ``AppConfig.ready()`` may run
    twice. Pass a module-level function rather than a ``lambda`` built per call,
    which would be a second reader. Raises ``ImproperlyConfigured`` for:

    - something that is not an exception class;
    - a class already registered with a different reader, which keeps the
      first;
    - a class the kernel already re-roots, or one wider than such a class: a
      ``ServiceValidationError`` or ``InvalidArguments``, or Django's
      ``ValidationError``, ``ValueError`` or ``TypeError``. A narrower one would
      never be asked, and a wider one, ``Exception`` at its widest, would read
      the caller's own bug in a row service as a refusal of the arguments.
      Each of the five is refused by its own case of
      ``test_a_class_the_kernel_already_reads_is_refused``, and the wider
      direction by ``test_a_class_wider_than_one_the_kernel_reads_is_refused``.

    Registrations are process-wide, as the relation specs that read them are,
    and there is no removal: an adapter registers for the life of the process.
    """
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
