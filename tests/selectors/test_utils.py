"""Tests for the private helpers in selectors/utils.py."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from django_service_specs.selectors.utils import call_selector, is_queryset, materialize_retrieve


def _sync_fn(*, value: int) -> int:
    return value * 2


async def _async_fn(*, value: int) -> int:
    return value * 3


class TestCallSelector:
    def test_sync(self) -> None:
        assert call_selector(_sync_fn, {"value": 5}) == 10

    def test_async_bridged(self) -> None:
        assert call_selector(_async_fn, {"value": 5}) == 15


class TestIsQueryset:
    @pytest.mark.django_db
    def test_a_queryset_is_a_queryset(self) -> None:
        assert is_queryset(User.objects.all()) is True

    @pytest.mark.django_db
    def test_a_manager_is_a_queryset(self) -> None:
        assert is_queryset(User.objects) is True

    def test_anything_else_is_not(self) -> None:
        assert is_queryset([1, 2, 3]) is False
        assert is_queryset(object()) is False
        assert is_queryset(None) is False


@pytest.mark.django_db
class TestMaterializeRetrieve:
    """The exported rule for what a ``RETRIEVE`` selector's return resolves to."""

    def test_a_queryset_resolves_to_its_first_row(self) -> None:
        user = User.objects.create(username="only")
        assert materialize_retrieve(User.objects.filter(pk=user.pk)) == user

    def test_an_empty_queryset_resolves_to_none(self) -> None:
        assert materialize_retrieve(User.objects.none()) is None

    def test_anything_else_is_already_the_row(self) -> None:
        row = object()
        assert materialize_retrieve(row) is row
