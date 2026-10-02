"""``enforce_affordances`` - refuse a call whose declared affordances are not met."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model

from django_service_specs.affordances.utils import (
    affordance_expression,
    answer_operation_condition,
)
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition


def enforce_affordances(
    spec: ServiceSpec,
    pool: dict[str, Any],
    *,
    instance: Any,
    reserved: frozenset[str] = RESERVED_POOL_SEEDS,
) -> None:
    """Refuse the call if one of the spec's ``affordances`` is not met.

    A transport that runs a service itself - a chain that owns the transaction
    and hands each step its own pool, say - calls this exactly as it calls
    [`authorize`][django_service_specs.authorization.authorize.authorize], or a
    condition is skipped on that path. ``pool`` is the keyword pool the service
    is about to receive and ``instance`` its resolved target, ``None`` for an
    operation with none. It raises
    [`ActionUnavailable`][django_service_specs.services.action_unavailable.ActionUnavailable]
    carrying the unmet affordance's ``reason`` and ``code``.

    Callers must invoke this **after** object-level authorization and
    validation, and **before** the service: class-level authorization -> target
    resolution -> object-level authorization -> validation -> affordances ->
    service. After access because a refusal describes the row's state, and
    telling a caller who may not see the row what state it is in is a
    disclosure.

    Declaration order decides which refusal a caller sees, and nothing past the
    first unmet condition runs. Every condition on the row is answered together
    by one query the first time one is reached. A callable condition sees the
    seeds of ``pool`` - never the call's target, input or client arguments - so
    a ``**kwargs`` catch-all is held to the same rule the declaration enforces on
    a named parameter. ``reserved`` is this call's seed set, registered seeds
    included: ``seeds.reserved`` for the
    [`PoolSeeds`][django_service_specs.pool.pool_seeds.PoolSeeds] the pool was
    built with. A callable's result is read for truth, so one that returns
    nothing refuses rather than allows.

    Raises:
        ActionUnavailable: An affordance is not met.
        ServiceNotFound: A condition on the row was reached and the row is gone:
            resolved a moment ago, and there is now nothing to do it to.
        ImproperlyConfigured: A condition on the row was reached and
            ``instance`` is not a model instance.
    """
    affordances: Sequence[Affordance] | None = spec.affordances
    if not affordances:
        return
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
    """Every row condition's answer for ``instance``, by declaration index, in one query.

    The same expression a list projection annotates, narrowed to one primary
    key, so a row reported available is the row this check lets through.
    """
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
        # Resolved a moment ago and gone now: the answer to "can this be done to
        # it" is that there is nothing to do it to.
        raise ServiceNotFound()
    return {index: bool(flag) for index, flag in zip(aliases.values(), row, strict=True)}
