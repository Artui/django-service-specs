"""Helpers shared across ``filters/`` and the selector that applies a FilterSet."""

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
