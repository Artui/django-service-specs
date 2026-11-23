from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.apps import apps
from django.db import connection, models


def _forget_range_validators() -> None:
    # A model field reads the range into its validators once and caches them.
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, models.IntegerField):
                field.__dict__.pop("validators", None)


@pytest.fixture
def unstated_ranges(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No integer column states a range, as on Django 4.2's SQLite, so the kernel refuses."""
    monkeypatch.setattr(
        type(connection.ops), "integer_field_range", lambda self, internal_type: (None, None)
    )
    _forget_range_validators()
    yield
    _forget_range_validators()
