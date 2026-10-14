from __future__ import annotations

import sys

import django_filters
import pytest

from django_service_specs.adapters.filters.utils import import_django_filters, range_suffixes


def test_it_is_django_filter_when_installed() -> None:
    assert import_django_filters() is django_filters


def test_without_django_filter_the_error_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "django_filters", None)
    with pytest.raises(ImportError, match=r"django-service-specs\[filter\]"):
        import_django_filters()


def test_a_range_filter_s_suffixes_are_the_keys_its_widget_reads() -> None:
    assert range_suffixes(django_filters.RangeFilter()) == ("min", "max")
    assert range_suffixes(django_filters.DateFromToRangeFilter()) == ("after", "before")


def test_any_other_filter_has_none() -> None:
    assert range_suffixes(django_filters.NumberFilter()) == ()
