from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.types.is_async import is_async
from django_service_specs.types.utils import PER_CALL_POOL_NAMES, is_row_condition


@dataclass(frozen=True)
class Affordance:
    """What can be done to this object right now, declared once on the operation."""

    code: str
    reason: str
    when: Any

    def __post_init__(self) -> None:
        # Refuses anything but a non-empty string name; each disjunct has its own test.
        for field_name in ("code", "reason"):
            value: Any = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ImproperlyConfigured(
                    f"Affordance.{field_name} must be a non-empty string; got {value!r}."
                )
        if is_row_condition(self.when):
            if not getattr(self.when, "conditional", False):
                raise ImproperlyConfigured(
                    f"Affordance {self.code!r}: `when` is an ORM expression but not a "
                    f"boolean one ({self.when!r}). Use a Q, an Exists, a lookup, or an "
                    "expression with output_field=BooleanField()."
                )
            return
        if not callable(self.when):
            raise ImproperlyConfigured(
                f"Affordance {self.code!r}: `when` must be an ORM boolean expression "
                f"(a condition on the row) or a callable (a condition on nothing in "
                f"particular); got {type(self.when).__name__}."
            )
        _refuse_async(self.code, self.when)
        _refuse_per_call_names(self.code, self.when)


def _refuse_async(code: str, when: Callable[..., Any]) -> None:
    """Refuse a condition that answers with something still to be awaited."""
    if is_async(when) or inspect.isasyncgenfunction(when):
        name = getattr(when, "__qualname__", None) or type(when).__name__
        raise ImproperlyConfigured(
            f"Affordance {code!r}: `when` is an async callable ({name}). A condition is "
            "sync-only and is never awaited, and an unawaited answer is truthy, so it "
            "would read every unmet condition as met; declare it with def."
        )


def _refuse_per_call_names(code: str, when: Callable[..., Any]) -> None:
    named = sorted(PER_CALL_POOL_NAMES.intersection(inspect.signature(when).parameters))
    if not named:
        return
    if "instance" in named:
        raise ImproperlyConfigured(
            f"Affordance {code!r}: `when` is a callable that reads `instance`. A "
            "condition on the row must be an ORM expression - a Q or an Exists - so "
            "it can be evaluated for a whole list in one query. A rule the ORM cannot "
            "express belongs in the service, where it is enforced and not advertised."
        )
    raise ImproperlyConfigured(
        f"Affordance {code!r}: `when` reads {', '.join(repr(n) for n in named)}, which "
        "exist only once a call is being made. An affordance is answerable without "
        "attempting the call; a rule about this call's target or input belongs in "
        "the service."
    )
