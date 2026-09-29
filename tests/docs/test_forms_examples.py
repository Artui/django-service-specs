"""The forms adapter page's examples, run.

``docs/forms.md`` includes its code from ``docs/examples/forms_adapter.py``,
and these tests run that code, so the page cannot describe behaviour the
adapter does not have. Where the page states an outcome - what a form
declares, a refusal's tree, what an update saves - the assertion here is that
statement.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from django_service_specs import InvalidArguments, NotPermitted, ValidationContext, dispatch
from docs.examples import forms_adapter
from tests.adapter_app.models import Author


def make_user(username: str, **extra: Any) -> Any:
    return get_user_model().objects.create_user(username=username, **extra)


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def bob() -> Any:
    return make_user("bob")


CONTEXT = ValidationContext(principal=None)


@pytest.mark.django_db
class TestForm:
    def test_the_form_declares_what_the_page_says(self) -> None:
        params = forms_adapter.book_validator.parameters()
        assert [
            (p.name, p.type, p.format, p.items, p.choices, p.required, p.nullable, p.help)
            for p in params
        ] == [
            ("title", "string", None, None, None, True, False, "As printed on the cover."),
            ("price", "string", "decimal", None, None, True, False, None),
            ("status", "string", None, None, ("draft", "published"), True, False, None),
            ("published_on", "string", "date", None, None, False, True, None),
            ("author", "integer", None, None, None, True, False, None),
            ("shelves", "array", None, "string", ("fiction", "poetry"), False, True, None),
        ]

    def test_it_validates_to_what_the_form_cleans(self) -> None:
        author = Author.objects.create(name="Ada")
        cleaned = forms_adapter.book_validator.validate(
            {
                "title": "Notes",
                "price": 12.5,
                "status": "published",
                "published_on": "1843-10-01",
                "author": author.pk,
                "shelves": ["poetry"],
            },
            CONTEXT,
        )
        assert cleaned == {
            "title": "Notes",
            "price": Decimal("12.5"),
            "status": "published",
            "published_on": date(1843, 10, 1),
            "author": author,
            "shelves": ["poetry"],
        }

    def test_the_forms_own_rule_is_a_message_about_the_whole_call(self) -> None:
        author = Author.objects.create(name="Ada")
        with pytest.raises(InvalidArguments) as refused:
            forms_adapter.book_validator.validate(
                {"title": "Notes", "price": "12.50", "status": "published", "author": author.pk},
                CONTEXT,
            )
        assert refused.value.detail == {
            "non_field_errors": ["A published book needs its publication date."]
        }


@pytest.mark.django_db
class TestModelForm:
    def test_the_owner_renames_themselves(self, ada: Any) -> None:
        dispatch(
            forms_adapter.rename_user_spec,
            principal=ada,
            arguments={"pk": ada.pk, "username": "lovelace"},
        )
        ada.refresh_from_db()
        assert ada.username == "lovelace"

    def test_keeping_their_own_name_is_not_a_clash(self, ada: Any) -> None:
        # The form's uniqueness check excludes the row being updated.
        dispatch(
            forms_adapter.rename_user_spec,
            principal=ada,
            arguments={"pk": ada.pk, "username": "ada"},
        )
        ada.refresh_from_db()
        assert ada.username == "ada"

    def test_another_users_name_is_refused_in_the_forms_words(self, ada: Any, bob: Any) -> None:
        with pytest.raises(InvalidArguments) as refused:
            dispatch(
                forms_adapter.rename_user_spec,
                principal=ada,
                arguments={"pk": ada.pk, "username": "bob"},
            )
        assert refused.value.detail == {"username": ["A user with that username already exists."]}
        ada.refresh_from_db()
        assert ada.username == "ada"

    def test_nobody_renames_someone_else(self, ada: Any, bob: Any) -> None:
        with pytest.raises(NotPermitted):
            dispatch(
                forms_adapter.rename_user_spec,
                principal=bob,
                arguments={"pk": ada.pk, "username": "bob2"},
            )
