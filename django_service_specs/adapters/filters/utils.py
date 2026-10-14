"""Helpers shared across ``adapters/filters/`` and the selector that applies a FilterSet."""

from __future__ import annotations

from typing import Any


def import_django_filters() -> Any:
    """django-filter, or an ``ImportError`` naming the extra that installs it."""
    # Function-local under the optional-dependency exemption: the package never
    # imports django-filter at the top (a ``filter_set`` is read and applied
    # by its attributes), and only reading a declared filter's kind needs its
    # classes.
    try:
        import django_filters
    except ImportError as exc:
        raise ImportError(
            "Reading a FilterSet's filters requires the `django-filter` package. "
            'Install it with `pip install "django-service-specs[filter]"`.'
        ) from exc
    return django_filters


def range_suffixes(filter_obj: Any) -> tuple[str, ...]:
    """The suffixes of the keys a range filter reads, one per bound, or none for any other filter.

    ``price_min`` and ``price_max`` for a ``RangeFilter`` called ``price``:
    its widget names the keys it reads, and nothing else in django-filter
    carries ``suffixes``. Read off the field class rather than ``.field``,
    which would build the form field and, for a related-row filter, its
    queryset. Shared by the Parameters a range filter is read as and by the
    selector, which refuses a bound at the argument that carried it.
    """
    return tuple(getattr(getattr(filter_obj.field_class, "widget", None), "suffixes", None) or ())
