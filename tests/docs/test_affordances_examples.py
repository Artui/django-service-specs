"""The affordances page's example, run.

Each test is a statement the page makes about ``docs/examples/affordances.py``.
The page's JSON blocks are read back and compared with what ``error_response``
answers for the refusals the example raises, so neither can drift from the
other.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import (
    ActionUnavailable,
    AdditionalInputRequired,
    NotPermitted,
    ServiceNotFound,
    error_response,
    operation_affordances,
)
from docs.examples import affordances
from tests.dispatch_app.models import Note

ROOT = Path(__file__).resolve().parents[2]


def json_blocks() -> list[Any]:
    page = (ROOT / "docs" / "affordances.md").read_text()
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", page, re.DOTALL)]


def body(exc: ActionUnavailable | AdditionalInputRequired) -> tuple[int, Any]:
    response = error_response(exc)
    return response.status_code, json.loads(response.content)


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.fixture
def read_only(settings: Any) -> None:
    settings.NOTES_READ_ONLY = True


@pytest.mark.django_db
class TestEnforcing:
    def test_a_live_note_is_renamed(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        assert affordances.rename_step(ada, note, "Final").title == "Final"
        note.refresh_from_db()
        assert note.title == "Final"

    def test_an_archived_note_is_refused_with_the_code_and_left_alone(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        with pytest.raises(ActionUnavailable) as refused:
            affordances.rename_step(ada, note, "Final")
        assert refused.value.code == "note_archived"
        assert refused.value.message == "An archived note cannot be renamed. Restore it first."
        note.refresh_from_db()
        assert note.title == "Draft"

    @pytest.mark.usefixtures("read_only")
    def test_the_condition_declared_first_answers_first(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        with pytest.raises(ActionUnavailable) as refused:
            affordances.rename_step(ada, note, "Final")
        assert refused.value.code == "notes_read_only"

    def test_a_principal_who_may_not_touch_the_row_learns_nothing_of_its_state(self) -> None:
        owner = get_user_model().objects.create_user(username="owner")
        bob = get_user_model().objects.create_user(username="bob")
        note = Note.objects.create(owner=owner, title="Draft", archived=True)
        with pytest.raises(NotPermitted):
            affordances.rename_step(bob, note, "Mine now")

    def test_the_row_is_read_from_the_table_not_from_the_instance(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        Note.objects.filter(pk=note.pk).update(archived=True)
        with pytest.raises(ActionUnavailable):
            affordances.rename_step(ada, note, "Final")

    def test_a_row_that_vanished_is_not_found(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        Note.objects.filter(pk=note.pk).delete()
        with pytest.raises(ServiceNotFound):
            affordances.rename_step(ada, note, "Final")

    def test_the_page_shows_the_409_error_response_answers(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft", archived=True)
        with pytest.raises(ActionUnavailable) as refused:
            affordances.rename_step(ada, note, "Final")
        assert body(refused.value) == (409, json_blocks()[0])


@pytest.mark.django_db
class TestOffering:
    def test_everything_is_offered_while_every_condition_holds(self, ada: Any) -> None:
        assert affordances.tools_for(ada) == {"list_notes": None, "rename_note": None}

    @pytest.mark.usefixtures("read_only")
    def test_an_unmet_callable_withholds_its_operation(self, ada: Any) -> None:
        assert affordances.tools_for(ada) == {"list_notes": None, "rename_note": "notes_read_only"}

    def test_a_condition_on_the_row_is_not_asked(
        self, ada: Any, django_assert_num_queries: Any
    ) -> None:
        Note.objects.create(owner=ada, title="Draft", archived=True)
        with django_assert_num_queries(0):
            assert affordances.tools_for(ada)["rename_note"] is None

    def test_operation_affordances_names_what_would_be_asked(self) -> None:
        read_only, _archived = affordances.rename_spec.affordances or ()
        assert operation_affordances(affordances.rename_spec) == (read_only,)
        assert operation_affordances(affordances.list_notes_spec) == ()


@pytest.mark.django_db
class TestAskingForOneMoreValue:
    def test_more_than_one_note_asks_first(self, ada: Any) -> None:
        for title in ("a", "b"):
            Note.objects.create(owner=ada, title=title, archived=True)
        with pytest.raises(AdditionalInputRequired) as asked:
            affordances.purge(ada, {})
        assert asked.value.schema == {"confirmed": {"type": "boolean"}}
        assert Note.objects.count() == 2

    def test_the_answer_comes_back_as_an_ordinary_argument(self, ada: Any) -> None:
        for title in ("a", "b"):
            Note.objects.create(owner=ada, title=title, archived=True)
        Note.objects.create(owner=ada, title="kept")
        assert affordances.purge(ada, {"confirmed": True}) == 2
        assert list(Note.objects.values_list("title", flat=True)) == ["kept"]

    def test_one_note_needs_no_confirmation(self, ada: Any) -> None:
        Note.objects.create(owner=ada, title="a", archived=True)
        assert affordances.purge(ada, {}) == 1

    def test_the_page_shows_the_422_error_response_answers(self, ada: Any) -> None:
        for title in ("a", "b"):
            Note.objects.create(owner=ada, title=title, archived=True)
        with pytest.raises(AdditionalInputRequired) as asked:
            affordances.purge(ada, {})
        assert body(asked.value) == (422, json_blocks()[1])

    def test_the_page_shows_exactly_two_bodies(self) -> None:
        assert len(json_blocks()) == 2


def test_idempotent_is_declared() -> None:
    assert affordances.rename_spec.idempotent is True


def test_a_list_names_each_answer_after_the_entry_and_the_code() -> None:
    spec = affordances.list_notes_with_answers_spec
    assert spec.affordances == {"rename": affordances.rename_spec}
    for name in ("affordance__rename__notes_read_only", "affordance__rename__note_archived"):
        with pytest.raises(ImproperlyConfigured, match=f"generates the annotation '{name}'"):
            replace(spec, annotations={name: None})
