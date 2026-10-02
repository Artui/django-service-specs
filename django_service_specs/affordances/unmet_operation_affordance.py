"""``unmet_operation_affordance`` - whether an operation should be offered at all."""

from __future__ import annotations

from typing import Any

from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.utils import answer_operation_condition
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance


def unmet_operation_affordance(
    spec: ServiceSpec | SelectorSpec,
    pool: dict[str, Any],
    *,
    reserved: frozenset[str] = RESERVED_POOL_SEEDS,
) -> Affordance | None:
    """The first of the spec's operation-scope affordances not met now, or ``None``.

    For a transport deciding whether to offer an operation at all, before anyone
    attempts it: an MCP server building its tool list, an agent assembling the
    toolset for its next step. An operation whose answer is an
    [`Affordance`][django_service_specs.types.affordance.Affordance] cannot be
    called right now whatever it is called with, so offering it only invites a
    refusal.

    Only the callable conditions are asked - the ones answered without a row. A
    condition on the row is skipped without being evaluated, because at list
    time there is no row: it runs no query and needs no instance, and it goes on
    being answered per object where it always is, at the call. The callables are
    asked in declaration order and the first unmet one is returned, which is the
    one a call would be refused with when no row condition before it answers
    first. A callable's result is read for truth, so one that returns nothing is
    unmet here as it is refused at the call. An exception it raises propagates:
    this answers the question, and a condition that cannot be answered is not a
    ``no``.

    **Build ``pool`` the way the call's would be.** A condition sees the seeds of
    it, never a client argument, through the same definition the call is
    refused by, so the two see the same names only if they are handed the same
    seeds:
    [`base_pool`][django_service_specs.pool.base_pool.base_pool] with the same
    ``seeds=``, and ``reserved=seeds.reserved`` here, or a condition reading a
    registered seed is asked without it.

    **The answer is advisory.** Enforcement at the call
    ([`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances])
    remains the authority, so a list built a moment before a condition flips is
    answered, when the stale entry is called, by an
    [`ActionUnavailable`][django_service_specs.services.action_unavailable.ActionUnavailable]
    carrying the ``code`` this would return if asked again then (or a row
    condition's, where one declared earlier refuses first). A condition driven by
    a clock has no event: it is answered when asked, and nothing announces the
    moment it flips. A transport that can push list changes to its client needs
    something else to tell it when to ask again.

    A ``SelectorSpec`` is accepted and answers ``None``: its ``affordances`` maps
    names to *other* operations, to be answered for its rows, and is never a
    condition on the selector itself - so a transport passes whatever spec it
    holds rather than branching on its type and risking reading that mapping as
    the selector's own.
    """
    for affordance in operation_affordances(spec):
        if not answer_operation_condition(affordance.when, pool, reserved=reserved):
            return affordance
    return None
