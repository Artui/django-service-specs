from __future__ import annotations

from typing import Any

import pytest
from django.db.models import Q
from django.utils.functional import SimpleLazyObject

from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, Record, make_user

NAMED = Affordance(code="unnamed", reason="Give the account a name first.", when=~Q(first_name=""))


def the_principal(*, user: Any) -> Any:
    return user


def lazy(user: Any) -> Any:
    """``request.user`` as Django's auth middleware hands it over: a proxy over a saved row."""
    return SimpleLazyObject(lambda: type(user).objects.get(pk=user.pk))


def my_profile(service: Any) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=the_principal),
        affordances=[NAMED],
    )


@pytest.mark.django_db
class TestALazyTargetRow:
    def test_a_row_condition_that_holds_runs_the_service(self) -> None:
        service = Record(returns="ran")

        user = make_user("ada")
        user.first_name = "Ada"
        user.save()

        result = dispatch(my_profile(service), principal=lazy(user), arguments={})

        assert result.value == "ran"
        assert len(service.calls) == 1

    def test_a_row_condition_that_fails_refuses_the_call(self) -> None:
        user = make_user("ada")
        service = Record()

        with pytest.raises(ActionUnavailable) as refused:
            dispatch(my_profile(service), principal=lazy(user), arguments={})

        assert refused.value.code == "unnamed"
        assert service.calls == []

    def test_a_selector_answers_a_row_condition_on_a_lazy_row(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=the_principal,
            permissions=OPEN,
            affordances={"rename": ServiceSpec(service=print, affordances=[NAMED])},
        )

        user = make_user("ada")
        user.first_name = "Ada"
        user.save()

        row = dispatch(spec, principal=lazy(user), arguments={}).value

        assert row_affordance_answers(spec, row) == {"rename": {"available": True}}
