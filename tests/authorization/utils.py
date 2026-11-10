from __future__ import annotations

import inspect
from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.utils import QUESTIONS


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
    """Answers every level with the object it was built with, from a plain ``def``."""

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


class Answers(PermissionCheck):
    """Answers each question as it was built to, writing ``name.method`` to ``log`` when asked."""

    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        permission: Any = True,
        row: Any = True,
        scope: Any = True,
    ) -> None:
        self.name, self.log = name, log
        self.permission, self.row, self.scope = permission, row, scope

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.log.append(f"{self.name}.has_permission")
        return self.permission

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.log.append(f"{self.name}.has_object_permission")
        return self.row

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        self.log.append(f"{self.name}.has_scope_permission")
        return self.scope


class ClassLevel(PermissionCheck):
    """Answers the class-level question alone, as built."""

    def __init__(self, name: str, log: list[str], *, permission: Any = True) -> None:
        self.name, self.log, self.permission = name, log, permission

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.log.append(f"{self.name}.has_permission")
        return self.permission


def opting_into(name: str, method: str) -> PermissionCheck:
    """A check passing every question, whose ``method`` declares ``*, <name>``."""
    positional = dict(QUESTIONS)[method]

    def declaring(self: PermissionCheck, *args: Any, **kwargs: Any) -> bool:
        return True

    parameters = [
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        *(
            inspect.Parameter(f"_{letter}", inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for letter in "abc"[:positional]
        ),
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY),
    ]
    declaring.__signature__ = inspect.Signature(parameters)
    namespace = {"has_permission": lambda self, principal, spec: True, method: declaring}
    return type(f"Opts{method}", (PermissionCheck,), namespace)()
