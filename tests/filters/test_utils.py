from __future__ import annotations

import sys

import django_filters
import pytest

from django_service_specs.filters.utils import import_django_filters


def test_it_is_django_filter_when_installed() -> None:
    assert import_django_filters() is django_filters


def test_without_django_filter_the_error_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "django_filters", None)
    with pytest.raises(ImportError, match=r"django-service-specs\[filter\]"):
        import_django_filters()
