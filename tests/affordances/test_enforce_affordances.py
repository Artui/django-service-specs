"""``enforce_affordances``: refuse a call whose declared affordances are not met.

Called directly, with a pool shaped as dispatch shapes a service's - the
seeds, the validated values spread by name, ``data`` and the target - which
is what a transport running a service itself hands it.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import PK, TENANT_SEEDS, make_user, note_by_pk
from tests.dispatch_app.models import LiveNote, Note

NOT_ARCHIVED = Affordance(
    code="note_archived", reason="An archived note cannot be renamed.", when=Q(archived=False)
)
TITLED = Affordance(code="untitled", reason="Give it a title first.", when=~Q(title=""))


def spec_with(*affordances: Affordance) -> ServiceSpec:
    return ServiceSpec(
        service=print,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
        ),
        affordances=list(affordances),
    )


def pool_for(user: Any, instance: Any) -> dict[str, Any]:
    data = {"title": "Final"}
    pool = base_pool(user=user, seeds=TENANT_SEEDS)
    pool.update({**data, "data": data, "instance": instance})
    return pool


def refusal(spec: ServiceSpec, pool: dict[str, Any], instance: Any) -> ActionUnavailable:
    with pytest.raises(ActionUnavailable) as refused:
        enforce_affordances(spec, pool, instance=instance, reserved=TENANT_SEEDS.reserved)
    return refused.value


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def note(ada: Any) -> Note:
    return Note.objects.create(owner=ada, title="Draft")


@pytest.mark.django_db
class TestNothingDeclared:
    def test_none_costs_nothing(self, ada: Any, note: Note, django_assert_num_queries: Any) -> None:
        spec = ServiceSpec(service=print)
        with django_assert_num_queries(0):
            assert enforce_affordances(spec, pool_for(ada, note), instance=note) is None

    def test_an_empty_sequence_costs_nothing(
        self, ada: Any, django_assert_num_queries: Any
    ) -> None:
        # No row is needed either: ``instance`` is never looked at.
        with django_assert_num_queries(0):
            enforce_affordances(spec_with(), pool_for(ada, None), instance=None)


@pytest.mark.django_db
class TestRowConditions:
    def test_a_met_condition_lets_the_call_through(self, ada: Any, note: Note) -> None:
        enforce_affordances(spec_with(NOT_ARCHIVED), pool_for(ada, note), instance=note)

    def test_an_unmet_condition_refuses_with_its_reason_and_code(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        refused = refusal(spec_with(NOT_ARCHIVED), pool_for(ada, note), note)
        assert refused.message == "An archived note cannot be renamed."
        assert refused.code == "note_archived"

    def test_the_row_is_read_from_the_table_not_from_the_instance(self, ada: Any) -> None:
        # The instance in hand still says "not archived"; the table says
        # otherwise, and the table is what the condition reads.
        note = Note.objects.create(owner=ada, title="Draft")
        Note.objects.filter(pk=note.pk).update(archived=True)
        assert refusal(spec_with(NOT_ARCHIVED), pool_for(ada, note), note).code == "note_archived"

    def test_every_row_condition_is_answered_by_one_query(
        self, ada: Any, note: Note, django_assert_num_queries: Any
    ) -> None:
        spec = spec_with(NOT_ARCHIVED, TITLED, Affordance(code="c", reason="r", when=lambda: True))
        with django_assert_num_queries(1):
            enforce_affordances(spec, pool_for(ada, note), instance=note)

    def test_a_condition_spans_relations_as_filter_does(self, ada: Any, note: Note) -> None:
        active_owner = Affordance(code="owner_gone", reason="r", when=Q(owner__is_active=True))
        spec = spec_with(active_owner)
        enforce_affordances(spec, pool_for(ada, note), instance=note)
        type(ada).objects.filter(pk=ada.pk).update(is_active=False)
        assert refusal(spec, pool_for(ada, note), note).code == "owner_gone"

    def test_a_row_the_default_manager_hides_is_still_answered(self, ada: Any) -> None:
        # Both reads go through ``_base_manager``: the narrowing to the one row,
        # and the correlated condition. Through the default manager, this row
        # would be not-found or unavailable, though the caller holds it.
        hidden = LiveNote.objects.create(owner=ada, title="Draft", archived=True)
        assert not LiveNote.objects.filter(pk=hidden.pk).exists()
        spec = spec_with(TITLED)
        enforce_affordances(spec, pool_for(ada, hidden), instance=hidden)

    def test_a_row_that_vanished_is_not_found(self, ada: Any, note: Note) -> None:
        Note.objects.filter(pk=note.pk).delete()
        with pytest.raises(ServiceNotFound):
            enforce_affordances(spec_with(NOT_ARCHIVED), pool_for(ada, note), instance=note)

    @pytest.mark.parametrize("instance", [None, {"pk": 1}], ids=["none", "mapping"])
    def test_a_target_that_is_not_a_model_instance_is_a_misconfiguration(
        self, ada: Any, instance: Any
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            enforce_affordances(spec_with(NOT_ARCHIVED), pool_for(ada, instance), instance=instance)
        assert str(refused.value).startswith(
            "An affordance condition on the row needs a resolved model instance, and this "
            f"dispatch resolved {type(instance).__name__}."
        )


@pytest.mark.django_db
class TestCallableConditions:
    def test_a_met_condition_lets_the_call_through(self, ada: Any) -> None:
        spec = ServiceSpec(
            service=print, affordances=[Affordance(code="c", reason="r", when=lambda: True)]
        )
        enforce_affordances(spec, pool_for(ada, None), instance=None)

    def test_an_unmet_condition_refuses_with_its_reason_and_code(self, ada: Any) -> None:
        closed = Affordance(code="books_closed", reason="The books are closed.", when=lambda: 0)
        refused = refusal(
            ServiceSpec(service=print, affordances=[closed]), pool_for(ada, None), None
        )
        assert (refused.message, refused.code) == ("The books are closed.", "books_closed")

    def test_a_condition_returning_nothing_refuses(self, ada: Any) -> None:
        silent = Affordance(code="silent", reason="r", when=lambda: None)
        spec = ServiceSpec(service=print, affordances=[silent])
        assert refusal(spec, pool_for(ada, None), None).code == "silent"

    def test_a_catch_all_sees_the_seeds_and_never_the_call(self, ada: Any, note: Note) -> None:
        seen: dict[str, Any] = {}

        def when(**kwargs: Any) -> bool:
            seen.update(kwargs)
            return True

        spec = ServiceSpec(service=print, affordances=[Affordance(code="c", reason="r", when=when)])
        enforce_affordances(
            spec, pool_for(ada, note), instance=note, reserved=TENANT_SEEDS.reserved
        )
        assert seen == {"user": ada, "progress": null_progress, "tenant": "tenant-of-ada"}


@pytest.mark.django_db
class TestDeclarationOrder:
    def test_a_callable_declared_first_answers_before_any_query(
        self, ada: Any, django_assert_num_queries: Any
    ) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        closed = Affordance(code="books_closed", reason="r", when=lambda: False)
        with django_assert_num_queries(0):
            refused = refusal(spec_with(closed, NOT_ARCHIVED), pool_for(ada, note), note)
        assert refused.code == "books_closed"

    def test_a_row_condition_declared_first_answers_and_nothing_after_it_runs(
        self, ada: Any
    ) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        asked: list[str] = []

        def closed() -> bool:
            asked.append("closed")
            return False

        spec = spec_with(NOT_ARCHIVED, Affordance(code="books_closed", reason="r", when=closed))
        assert refusal(spec, pool_for(ada, note), note).code == "note_archived"
        assert asked == []

    def test_the_first_of_two_unmet_row_conditions_answers(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="", archived=True)
        assert refusal(spec_with(TITLED, NOT_ARCHIVED), pool_for(ada, note), note).code == (
            "untitled"
        )
