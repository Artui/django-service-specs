"""Tests for ``arun_service`` — async dispatch with optional atomic wrapping."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from django_service_specs.services.arun_service import arun_service


@pytest.mark.django_db(transaction=True)
class TestArunService:
    async def test_passes_kwargs_no_atomic(self) -> None:
        async def fn(*, value: int) -> int:
            return value * 2

        assert await arun_service(fn, {"value": 7}, atomic=False) == 14

    async def test_returns_value_atomic(self) -> None:
        async def fn() -> str:
            return "ok"

        assert await arun_service(fn, {}, atomic=True) == "ok"

    async def test_atomic_creates_persist(self) -> None:
        async def fn() -> Any:
            return await User.objects.acreate(username="persisted")

        user = await arun_service(fn, {}, atomic=True)
        assert user.pk is not None
        assert await User.objects.acount() == 1

    async def test_atomic_rolls_back_on_error(self) -> None:
        async def fn() -> None:
            await User.objects.acreate(username="oops")
            raise IntegrityError("boom")

        with pytest.raises(IntegrityError):
            await arun_service(fn, {}, atomic=True)

        assert await User.objects.acount() == 0
