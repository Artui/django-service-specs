"""``aenforce_affordances`` - the async twin of ``enforce_affordances``."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


async def aenforce_affordances(
    spec: ServiceSpec | SpecSource,
    pool: dict[str, Any],
    *,
    instance: Any,
    reserved: frozenset[str] = RESERVED_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
) -> None:
    """[`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances] for an async caller.

    For a transport that runs a service without
    [`adispatch`][django_service_specs.dispatch.adispatch.adispatch], which
    answers a spec's affordances inside its own hop. It refuses and lets through
    exactly as the sync function does, with the same arguments.

    A condition on the row is a query and a callable condition is user code
    that may query, and neither can run on the event loop. So every condition
    is answered in **one** ``sync_to_async(thread_sensitive=True)`` hop, as
    dispatch's async path runs every sync concept: not one hop per condition.
    A spec declaring none returns before the hop, so declaring nothing costs
    the async path nothing. ``spec`` may be a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource], read as
    the spec it compiles to, and a ``SelectorSpec`` is refused with the sync
    function's ``TypeError`` whatever it declares.

    Raises:
        ActionUnavailable: An affordance is not met.
        TypeError: ``spec`` is, or compiles to, a ``SelectorSpec``.
        ServiceNotFound: A condition on the row was reached and the row is gone.
        ImproperlyConfigured: A condition on the row was reached and
            ``instance`` is not a model instance.
    """
    compiled = kernel_spec(spec)
    # Only a ServiceSpec declaring nothing returns here: a SelectorSpec goes on
    # to the sync function, which refuses it, so the two refuse alike whatever
    # the selector declares. One arc to coverage, so each operand is named:
    # test_a_selector_spec_is_refused_as_the_sync_function_refuses_it holds the
    # kind, and test_an_unmet_condition_refuses_with_its_code_and_reason what is
    # declared.
    if isinstance(compiled, ServiceSpec) and not compiled.affordances:
        return
    await sync_to_async(enforce_affordances, thread_sensitive=True)(
        # ``spec`` rather than ``compiled``: the sync function compiles it again,
        # from the cache, to the same spec, and it is what its annotation takes.
        spec,
        pool,
        instance=instance,
        reserved=reserved,
        call_context=call_context,
    )
