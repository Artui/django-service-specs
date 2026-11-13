from __future__ import annotations

import inspect
from typing import Any, cast

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.utils import translation

from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.affordances.utils import books_closed, empty_reason, language_reason
from tests.dispatch.utils import TENANT_SEEDS, make_user
from tests.specs.utils import Foreign

UNAVAILABLE_ROW = Affordance(code="never", reason="No row is.", when=Q(pk__in=[]))


def closed(code: str) -> Affordance:
    return Affordance(code=code, reason=f"{code} is closed.", when=lambda: False)


def opened(code: str) -> Affordance:
    return Affordance(code=code, reason=f"{code} is open.", when=lambda: True)


def test_a_spec_declaring_nothing_is_offered() -> None:
    assert (
        unmet_operation_affordance(ServiceSpec(service=print), {}, reserved=RESERVED_POOL_SEEDS)
        is None
    )


def test_all_conditions_met_is_offered() -> None:
    spec = ServiceSpec(service=print, affordances=[opened("a"), opened("b")])
    assert unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS) is None


def test_the_first_unmet_condition_in_declaration_order_is_the_answer() -> None:
    first, second = closed("first"), closed("second")
    spec = ServiceSpec(service=print, affordances=[opened("a"), first, second])
    assert unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS) is first


@pytest.mark.django_db
def test_a_row_condition_is_skipped_without_a_query(
    django_assert_num_queries: Any,
) -> None:
    spec = ServiceSpec(service=print, affordances=[UNAVAILABLE_ROW, opened("a")])
    with django_assert_num_queries(0):
        assert unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS) is None


def test_a_condition_returning_nothing_is_unmet() -> None:
    silent = Affordance(code="silent", reason="Said nothing.", when=lambda: None)
    assert (
        unmet_operation_affordance(
            ServiceSpec(service=print, affordances=[silent]), {}, reserved=RESERVED_POOL_SEEDS
        )
        is silent
    )


def test_a_condition_that_cannot_be_answered_raises_rather_than_answering_no() -> None:
    def broken() -> bool:
        raise RuntimeError("The flag store is down.")

    spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=broken)])
    with pytest.raises(RuntimeError, match="The flag store is down."):
        unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS)


def test_reserved_is_required_not_defaulted() -> None:
    """A default would ask a condition with none of the registered seeds: no default is asked."""
    asked = cast(Any, unmet_operation_affordance)
    with pytest.raises(TypeError, match="reserved"):
        asked(ServiceSpec(service=print), {})


def test_a_selector_spec_is_offered_whatever_its_mapping_holds() -> None:
    rename = ServiceSpec(service=print, affordances=[closed("frozen")])
    selector = SelectorSpec(kind=SelectorKind.LIST, selector=list, affordances={"rename": rename})
    assert unmet_operation_affordance(selector, {}, reserved=RESERVED_POOL_SEEDS) is None


@pytest.mark.django_db
class TestTheSeedsAConditionSees:
    def test_a_registered_seed_is_seen_when_reserved_names_it(self) -> None:
        ada = make_user("ada")
        tenant_is_ada = Affordance(
            code="other_tenant", reason="r", when=lambda *, tenant: tenant == "tenant-of-ada"
        )
        spec = ServiceSpec(service=print, affordances=[tenant_is_ada])
        pool = base_pool(user=ada, seeds=TENANT_SEEDS)
        assert unmet_operation_affordance(spec, pool, reserved=TENANT_SEEDS.reserved) is None


def test_a_condition_answering_with_a_coroutine_is_refused_not_offered() -> None:
    answer = books_closed()
    spec = ServiceSpec(
        service=print,
        affordances=[Affordance(code="books_closed", reason="r", when=lambda: answer)],
    )
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
        unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS)
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_a_foreign_declaration_answers_what_its_compiled_spec_does() -> None:
    first = closed("first")
    spec = ServiceSpec(service=print, affordances=[opened("a"), first])
    assert unmet_operation_affordance(Foreign(spec), {}, reserved=RESERVED_POOL_SEEDS) is first


# The call's context: a transport asking ahead of a call has one to hand, or
# the condition gets a dict of its own rather than a TypeError.


def _naming_it(handed: list[Any]) -> ServiceSpec:
    def when(*, call_context: Any) -> bool:
        handed.append(call_context)
        return True

    return ServiceSpec(
        service=print,
        affordances=[
            Affordance(code="first", reason="r", when=when),
            Affordance(code="second", reason="r", when=when),
        ],
    )


def test_a_condition_naming_the_call_context_is_handed_the_dict_passed() -> None:
    handed: list[Any] = []
    context: dict[str, Any] = {}
    unmet_operation_affordance(
        _naming_it(handed), base_pool(user=None), call_context=context, reserved=RESERVED_POOL_SEEDS
    )
    assert len(handed) == 2
    assert all(seen is context for seen in handed)


def test_with_none_passed_its_conditions_share_a_fresh_dict() -> None:
    handed: list[Any] = []
    spec = _naming_it(handed)
    unmet_operation_affordance(spec, base_pool(user=None), reserved=RESERVED_POOL_SEEDS)
    unmet_operation_affordance(spec, base_pool(user=None), reserved=RESERVED_POOL_SEEDS)
    first, again, second, _ = handed
    assert first == {}
    assert again is first
    assert second is not first


def test_a_catch_all_condition_is_handed_the_seeds_and_never_the_call_context() -> None:
    seen: list[set[str]] = []

    def when(**kwargs: Any) -> bool:
        seen.append(set(kwargs))
        return True

    spec = ServiceSpec(service=print, affordances=[Affordance(code="a", reason="r", when=when)])
    unmet_operation_affordance(
        spec, base_pool(user=None), call_context={}, reserved=RESERVED_POOL_SEEDS
    )
    assert seen == [{"user", "progress"}]


def test_the_call_context_passed_else_the_pool_s_else_a_fresh_one() -> None:
    """A pool carrying the call's context is the call's own; a parameter naming it is welcome."""
    handed: list[Any] = []
    held: dict[str, Any] = {}
    pool = {**base_pool(user=None), "call_context": held}
    unmet_operation_affordance(_naming_it(handed), pool, reserved=RESERVED_POOL_SEEDS)
    unmet_operation_affordance(
        _naming_it(handed), pool, call_context=held, reserved=RESERVED_POOL_SEEDS
    )
    unmet_operation_affordance(
        _naming_it(handed), base_pool(user=None), reserved=RESERVED_POOL_SEEDS
    )
    from_pool, _, passed, _, fresh, _ = handed
    assert from_pool is held
    assert passed is held
    assert fresh == {}
    assert fresh is not held


def test_a_call_context_passed_beside_another_in_the_pool_is_refused() -> None:
    """Two claimants to one name, as dispatch refuses every other: neither is chosen quietly."""
    handed: list[Any] = []
    pool = {**base_pool(user=None), "call_context": {}}
    with pytest.raises(ImproperlyConfigured, match="call_context"):
        unmet_operation_affordance(
            _naming_it(handed), pool, call_context={}, reserved=RESERVED_POOL_SEEDS
        )
    assert handed == []


class TestTheCallSRequestAndView:
    """A condition declaring ``request`` or ``view`` reads the call's context, by default too."""

    def test_a_condition_reads_the_context_s_request_from_a_pool_holding_none(self) -> None:
        request = object()
        seen: list[Any] = []

        def when(*, request: Any, view: Any) -> bool:
            seen.append((request, view))
            return True

        spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=when)])
        assert (
            unmet_operation_affordance(
                spec,
                base_pool(user=None),
                call_context={"request": request},
                reserved=RESERVED_POOL_SEEDS,
            )
            is None
        )
        assert seen == [(request, None)]

    def test_the_pool_s_own_entry_outranks_the_context_s(self) -> None:
        """A pool built with a registered ``request`` seed is asked with that seed."""
        seen: list[Any] = []

        def when(*, request: Any) -> bool:
            seen.append(request)
            return True

        seeds = DEFAULT_POOL_SEEDS.extend(request=lambda: "registered")
        spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=when)])
        unmet_operation_affordance(
            spec,
            base_pool(user=None, seeds=seeds),
            reserved=seeds.reserved,
            call_context={"request": "context"},
        )
        assert seen == ["registered"]


class TestALazyReason:
    def test_the_answer_carries_it_as_text_in_the_language_active_at_the_call(self) -> None:
        unmet = Affordance(code="c", reason=language_reason(), when=lambda: False)
        spec = ServiceSpec(service=print, affordances=[unmet])
        with translation.override("fr"):
            answer = unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS)
        assert answer is not None
        assert (type(answer.reason), answer.reason, answer.code) == (str, "fr", "c")

    def test_one_that_resolves_empty_is_refused(self) -> None:
        unmet = Affordance(code="c", reason=empty_reason(), when=lambda: False)
        spec = ServiceSpec(service=print, affordances=[unmet])
        with pytest.raises(ImproperlyConfigured) as refused:
            unmet_operation_affordance(spec, {}, reserved=RESERVED_POOL_SEEDS)
        assert str(refused.value) == "Affordance.reason must be a non-empty string; got ''."
