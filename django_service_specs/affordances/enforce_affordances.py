from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model

from django_service_specs.affordances.utils import (
    affordance_expression,
    answer_operation_condition,
    with_call_context,
)
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition


def enforce_affordances(
    spec: ServiceSpec | SpecSource,
    pool: dict[str, Any],
    *,
    instance: Any,
    reserved: frozenset[str],
    call_context: dict[str, Any] | None = None,
) -> None:
    """Refuse the call if one of the spec's ``affordances`` is not met."""
    compiled = kernel_spec(spec)
    if not isinstance(compiled, ServiceSpec):
        raise TypeError(
            f"enforce_affordances() takes a ServiceSpec; got {type(compiled).__name__}, whose "
            "affordances are answers about each row rather than conditions on the call."
        )
    affordances: Sequence[Affordance] | None = compiled.affordances
    if not affordances:
        return
    pool = with_call_context(pool, call_context)
    row_flags: dict[int, bool] | None = None
    for index, affordance in enumerate(affordances):
        if is_row_condition(affordance.when):
            if row_flags is None:
                row_flags = _row_affordance_flags(instance, affordances)
            available: Any = row_flags[index]
        else:
            available = answer_operation_condition(affordance.when, pool, reserved=reserved)
        if not available:
            raise ActionUnavailable(affordance.reason, code=affordance.code)


def _row_affordance_flags(instance: Any, affordances: Sequence[Affordance]) -> dict[int, bool]:
    """Every row condition's answer for ``instance``, by declaration index, in one query."""
    if not isinstance(instance, Model):
        raise ImproperlyConfigured(
            "An affordance condition on the row needs a resolved model instance, and this "
            f"dispatch resolved {type(instance).__name__}. Declare row conditions only on "
            "an operation that targets one row, through an instance_selector_spec."
        )
    model = type(instance)
    aliases: dict[str, int] = {
        f"affordance__{index}": index
        for index, affordance in enumerate(affordances)
        if is_row_condition(affordance.when)
    }
    row = (
        model._base_manager.filter(pk=instance.pk)
        .annotate(
            **{
                alias: affordance_expression(model, affordances[index].when)
                for alias, index in aliases.items()
            }
        )
        .values_list(*aliases)
        .first()
    )
    if row is None:
        raise ServiceNotFound()
    return {index: bool(flag) for index, flag in zip(aliases.values(), row, strict=True)}
