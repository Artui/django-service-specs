from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import FilePresenter, SelectorKind, SelectorSpec, file_output
from docs.examples import files
from tests.adapter_app.models import Author, Book

pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.fixture
def book() -> Book:
    author = Author.objects.create(name="Le Guin")
    return Book.objects.create(author=author, title="Lathe of Heaven", price=Decimal("9.99"))


def test_a_service_s_file_is_served_under_its_own_name(ada: Any, book: Book) -> None:
    assert files.serve(files.export, ada) == {
        "name": "books.csv",
        "type": "text/csv",
        "body": b"title,price\r\nLathe of Heaven,9.99\r\n",
    }


def test_a_row_is_rendered_and_named_by_the_presenter(ada: Any, book: Book) -> None:
    assert files.serve(files.label, ada, pk=book.pk) == {
        "name": f"label-{book.pk}.txt",
        "type": "text/plain",
        "body": b"Lathe of Heaven\n9.99\n",
    }


def test_a_file_past_the_ceiling_is_answered_by_the_transport(ada: Any, book: Book) -> None:
    spec = SelectorSpec(
        kind=files.label.kind,
        selector=files.label.selector,
        reads=files.label.reads,
        permissions=files.label.permissions,
        presenter=FilePresenter("text/plain", filename="a.txt", render=lambda _: b"x" * 1_000_001),
    )

    assert files.serve(spec, ada, pk=book.pk) == {"error": "over 1000000 bytes"}


def test_a_json_spec_is_not_served_as_a_file(ada: Any) -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=files.label.selector)

    with pytest.raises(ValueError, match="Not a file spec"):
        files.serve(spec, ada)


def test_a_list_of_files_is_refused_at_registration() -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=files.label.selector, presenter=files.label.presenter
    )

    with pytest.raises(ImproperlyConfigured, match="presents a list of rows"):
        file_output(spec)
