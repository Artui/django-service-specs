"""``operation_affordances``: the conditions answerable without a row."""

from __future__ import annotations

from django.db.models import Q

from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance

FROZEN = Affordance(code="books_closed", reason="The books are closed.", when=lambda: False)
ARCHIVED = Affordance(code="note_archived", reason="Archived.", when=Q(archived=False))
QUIET = Affordance(code="quiet_hours", reason="Not now.", when=lambda *, user: True)


def test_the_callable_conditions_in_declaration_order() -> None:
    spec = ServiceSpec(service=print, affordances=[FROZEN, ARCHIVED, QUIET])
    assert operation_affordances(spec) == (FROZEN, QUIET)


def test_a_spec_declaring_none_answers_empty() -> None:
    assert operation_affordances(ServiceSpec(service=print)) == ()
    assert operation_affordances(ServiceSpec(service=print, affordances=[ARCHIVED])) == ()


def test_a_selector_answers_empty_whatever_its_mapping_holds() -> None:
    # Its mapping names other operations; reading their conditions as the
    # selector's own would answer a question about something else.
    rename = ServiceSpec(service=print, affordances=[FROZEN])
    selector = SelectorSpec(kind=SelectorKind.LIST, selector=list, affordances={"rename": rename})
    assert operation_affordances(selector) == ()
