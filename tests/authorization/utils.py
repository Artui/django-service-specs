"""Permission-check test doubles shared by the authorization function tests."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck


class Allow(PermissionCheck):
    """Passes at both levels, and records whether it was asked."""

    def __init__(self) -> None:
        self.class_level_calls = 0
        self.object_level_calls = 0

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.class_level_calls += 1
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.object_level_calls += 1
        return True


class Refuse(PermissionCheck):
    """Refuses at both levels, with the default message."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class RefuseWithMessage(PermissionCheck):
    """Refuses at both levels, naming its own message."""

    message = "Staff only."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class AnswersWith(PermissionCheck):
    """Answers every level with the object it was built with, from a plain ``def``.

    The shape construction cannot see: each method is sync, so a spec accepts
    the check, and what comes back is whatever the test handed in - a
    coroutine, as a decorated or partial-wrapped ``async def`` returns one.
    """

    def __init__(self, answer: Any) -> None:
        self.answer = answer

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return self.answer

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return self.answer

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return self.answer


async def refuses() -> bool:
    """Awaited, a refusal. Called sync, a coroutine, which is truthy."""
    return False


class NotACoroutine:
    """Awaitable through ``__await__`` alone: no ``close()`` to call on it."""

    def __await__(self) -> Any:
        yield
        return False


async def refuses_lazily() -> Any:
    """An async generator: not awaitable, never started, and truthy."""
    yield False


class SeesTheCall(PermissionCheck):
    """Passes at every level, recording the ``request`` and ``view`` each question is handed."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, Any, Any]] = []

    def has_permission(self, principal: Any, spec: Any, *, request: Any, view: Any) -> bool:
        self.seen.append(("has_permission", request, view))
        return True

    def has_object_permission(
        self, principal: Any, spec: Any, target: Any, *, request: Any, view: Any
    ) -> bool:
        self.seen.append(("has_object_permission", request, view))
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, request: Any, view: Any
    ) -> bool:
        self.seen.append(("has_scope_permission", request, view))
        return True
