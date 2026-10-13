from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.db import models

from django_service_specs.selectors.is_queryset import is_queryset


@pytest.mark.django_db
def test_a_queryset_is_a_queryset() -> None:
    assert is_queryset(User.objects.all()) is True


def test_a_manager_is_a_queryset() -> None:
    assert is_queryset(User.objects) is True


def test_a_manager_built_on_base_manager_is_one_too() -> None:
    manager = models.manager.BaseManager.from_queryset(models.QuerySet)()
    assert not isinstance(manager, models.Manager)
    assert is_queryset(manager) is True


def test_anything_else_is_not() -> None:
    assert is_queryset([1, 2, 3]) is False
    assert is_queryset(object()) is False
    assert is_queryset(None) is False
