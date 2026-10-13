"""The exported rule for what a RETRIEVE selector's return resolves to."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from django_service_specs.selectors.materialize_retrieve import materialize_retrieve


@pytest.mark.django_db
def test_a_queryset_resolves_to_its_first_row() -> None:
    user = User.objects.create(username="only")
    assert materialize_retrieve(User.objects.filter(pk=user.pk)) == user


@pytest.mark.django_db
def test_an_empty_queryset_resolves_to_none() -> None:
    assert materialize_retrieve(User.objects.none()) is None


def test_anything_else_is_already_the_row() -> None:
    row = object()
    assert materialize_retrieve(row) is row
