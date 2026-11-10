from __future__ import annotations

from typing import Any


def import_django_filters() -> Any:
    """django-filter, or an ``ImportError`` naming the extra that installs it."""
    try:
        import django_filters
    except ImportError as exc:
        raise ImportError(
            "Reading a FilterSet's filters requires the `django-filter` package. "
            'Install it with `pip install "django-service-specs[filter]"`.'
        ) from exc
    return django_filters


def range_suffixes(filter_obj: Any) -> tuple[str, ...]:
    """The key suffixes a range filter reads, one per bound; none otherwise."""
    return tuple(getattr(getattr(filter_obj.field_class, "widget", None), "suffixes", None) or ())
