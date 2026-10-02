"""Helpers every reader of an affordance answers through.

The call refusing an operation, a transport deciding whether to offer it, and a
list reporting it per row all ask the same conditions. Each question is answered
here once, so no two of them can disagree about which names a condition sees,
what counts as met, or which rows a condition on the row lets through.

The per-call names, the row-condition test and the answer's alias live in
``types/utils.py`` instead: ``Affordance`` and the specs read them at
construction, and ``types/`` is the one place they can import from without
loading this phase.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django.db.models import Exists, Model, OuterRef

from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.types.utils import PER_CALL_POOL_NAMES


def ambient_pool(pool: Mapping[str, Any], *, reserved: frozenset[str]) -> dict[str, Any]:
    """The part of a pool an affordance's callable condition may read.

    The seeds - ``user``, ``progress`` and whatever the project registered - and
    nothing else. Not the per-call names (the target, the validated input, and
    the values a later step adds), which would make the answer depend on
    attempting the call; and not a client argument spread into the pool, which
    would let the caller decide whether the operation is available. Filtering by
    the reserved set rather than by exclusion is what makes the second hold: a
    spread key is by construction not a seed, because dispatch refuses a
    parameter named after one.

    One definition, so a condition asked at the moment of a call and the same
    condition asked for a list see the same names.
    """
    # Two conjuncts, each held in tests/affordances/test_utils.py:
    # ``test_a_spread_argument_is_not_ambient`` fails without the first, and
    # ``test_a_per_call_name_is_not_ambient_although_it_is_reserved`` without
    # the second.
    return {
        key: value
        for key, value in pool.items()
        if key in reserved and key not in PER_CALL_POOL_NAMES
    }


def answer_operation_condition(
    when: Callable[..., Any], pool: Mapping[str, Any], *, reserved: frozenset[str]
) -> bool:
    """One callable affordance condition, answered against ``pool`` and read for truth.

    Three places ask a condition on nothing in particular: the call, refusing
    it (``enforce_affordances``); a list, projecting it onto every row; and a
    transport deciding whether to offer the operation at all
    (``unmet_operation_affordance``). All three answer it here, so they cannot
    disagree about which names the condition sees - the ``ambient_pool`` of
    whatever pool the caller holds, taken here rather than by each caller - nor
    about what counts as met: a callable that returns nothing is unmet in all
    three, not in two of them.
    """
    ambient = ambient_pool(pool, reserved=reserved)
    return bool(when(**resolve_callable_kwargs(when, ambient)))


def affordance_expression(model: type[Model], when: Any) -> Exists:
    """The SQL answer to one affordance condition, for whichever row it is annotated on.

    ``Exists(<the row, narrowed by pk>.filter(when))`` rather than the condition
    inline, for two reasons that both come from where this is spent. Inline, a
    condition spanning a multi-valued relation joins it into the outer query and
    **duplicates the rows** of the list it is annotated on, and an aggregate
    beside it counts across that join. Inside a correlated subquery the outer
    query gains no join at all. And the subquery gives the condition exactly the
    meaning it has in ``Model.objects.filter(when)``, which is the reading an
    author already has for a ``Q``.

    ``_base_manager`` because the subquery only re-finds a row that has already
    been resolved: a default manager that hides rows would answer "unavailable"
    for a row the caller is looking at.

    The single-object check and a list projection both annotate this one
    expression, so the two cannot disagree about any row. Being SQL, it reads the
    table and never a ``prefetch_related`` cache, so a filtered ``Prefetch`` on
    the same relation cannot hide rows from the answer.
    """
    return Exists(model._base_manager.filter(pk=OuterRef("pk")).filter(when))
