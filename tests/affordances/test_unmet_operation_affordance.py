"""``unmet_operation_affordance``: whether an operation should be offered at all."""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import Q

from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import TENANT_SEEDS, make_user

UNAVAILABLE_ROW = Affordance(code="never", reason="No row is.", when=Q(pk__in=[]))


def closed(code: str) -> Affordance:
    return Affordance(code=code, reason=f"{code} is closed.", when=lambda: False)


def opened(code: str) -> Affordance:
    return Affordance(code=code, reason=f"{code} is open.", when=lambda: True)


def test_a_spec_declaring_nothing_is_offered() -> None:
    assert unmet_operation_affordance(ServiceSpec(service=print), {}) is None


def test_all_conditions_met_is_offered() -> None:
    spec = ServiceSpec(service=print, affordances=[opened("a"), opened("b")])
    assert unmet_operation_affordance(spec, {}) is None


def test_the_first_unmet_condition_in_declaration_order_is_the_answer() -> None:
    first, second = closed("first"), closed("second")
    spec = ServiceSpec(service=print, affordances=[opened("a"), first, second])
    assert unmet_operation_affordance(spec, {}) is first


@pytest.mark.django_db
def test_a_row_condition_is_skipped_without_a_query(
    django_assert_num_queries: Any,
) -> None:
    spec = ServiceSpec(service=print, affordances=[UNAVAILABLE_ROW, opened("a")])
    with django_assert_num_queries(0):
        assert unmet_operation_affordance(spec, {}) is None


def test_a_condition_returning_nothing_is_unmet() -> None:
    silent = Affordance(code="silent", reason="Said nothing.", when=lambda: None)
    assert (
        unmet_operation_affordance(ServiceSpec(service=print, affordances=[silent]), {}) is silent
    )


def test_a_condition_that_cannot_be_answered_raises_rather_than_answering_no() -> None:
    def broken() -> bool:
        raise RuntimeError("The flag store is down.")

    spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=broken)])
    with pytest.raises(RuntimeError, match="The flag store is down."):
        unmet_operation_affordance(spec, {})


def test_a_selector_spec_is_offered_whatever_its_mapping_holds() -> None:
    rename = ServiceSpec(service=print, affordances=[closed("frozen")])
    selector = SelectorSpec(kind=SelectorKind.LIST, selector=list, affordances={"rename": rename})
    assert unmet_operation_affordance(selector, {}) is None


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

    def test_by_default_a_registered_seed_is_withheld(self) -> None:
        # The default is the kernel's own names, so a transport that built its
        # pool with registered seeds and did not pass ``reserved`` asks the
        # condition without them.
        ada = make_user("ada")
        seen: dict[str, Any] = {}

        def when(**kwargs: Any) -> bool:
            seen.update(kwargs)
            return True

        spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=when)])
        pool = base_pool(user=ada, seeds=TENANT_SEEDS)
        assert unmet_operation_affordance(spec, pool) is None
        assert seen == {"user": ada, "progress": null_progress}
