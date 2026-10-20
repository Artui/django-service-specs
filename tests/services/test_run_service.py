"""Tests for ``run_service`` — sync dispatch with optional atomic wrapping."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from django_service_specs.services.run_service import run_service


@pytest.mark.django_db(transaction=True)
class TestRunServiceSync:
    def test_passes_kwargs(self) -> None:
        def fn(*, x: int, y: int) -> int:
            return x + y

        assert run_service(fn, {"x": 2, "y": 3}, atomic=False) == 5

    @pytest.mark.parametrize("atomic", [False, True])
    def test_atomic_wraps_the_call_in_a_transaction(self, atomic: bool) -> None:
        captured: dict[str, bool] = {}

        def fn() -> None:
            captured["in_atomic"] = transaction.get_connection().in_atomic_block

        run_service(fn, {}, atomic=atomic)
        assert captured["in_atomic"] is atomic

    def test_atomic_rollback_on_exception(self) -> None:
        User.objects.create(username="seed")

        def fn() -> None:
            User.objects.create(username="will-rollback")
            raise IntegrityError("forced rollback")

        with pytest.raises(IntegrityError):
            run_service(fn, {}, atomic=True)

        assert User.objects.count() == 1

    def test_returns_value(self) -> None:
        def fn() -> str:
            return "ok"

        assert run_service(fn, {}, atomic=True) == "ok"

    def test_bridges_an_async_service(self) -> None:
        """The un-awaited-coroutine trap this bridge exists to close."""

        async def fn(*, value: int) -> int:
            return value * 2

        assert run_service(fn, {"value": 3}, atomic=False) == 6

    def test_bridges_an_async_service_atomically(self) -> None:
        async def fn() -> Any:
            return await User.objects.acreate(username="via-async-atomic")

        user = run_service(fn, {}, atomic=True)
        assert user.pk is not None
