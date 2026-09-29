"""The pydantic adapter page's examples, run.

As in ``test_examples.py``: the page includes its code from
``docs/examples/pydantic_adapter.py``, and where it states an outcome - what a
model declares, a refusal's tree, how deep a tree is described - the assertion
here is that statement.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from django_service_specs import (
    ChildCollectionChange,
    DataclassValidator,
    FieldAudience,
    InvalidArguments,
    Parameter,
    Parameters,
    ValidationContext,
    dispatch,
    present,
)
from docs.examples import declaring, pydantic_adapter
from tests.adapter_app.models import Author, Book

CONTEXT = ValidationContext(principal=None)


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


def _refusal(arguments: dict[str, Any], ada: Any) -> Any:
    with pytest.raises(InvalidArguments) as caught:
        dispatch(pydantic_adapter.create_author_spec, principal=ada, arguments=arguments)
    return caught.value.detail


def _category(depth: int, leaf: Any) -> dict[str, Any]:
    """A category ``depth`` levels deep, one child per level, the deepest named ``leaf``."""
    if depth == 1:
        return {"name": leaf}
    return {"name": f"level {depth}", "children": [_category(depth - 1, leaf)]}


@pytest.mark.django_db
class TestDeclaringWithModels:
    def test_a_create_writes_the_author_and_its_books_and_presents_them(self, ada: Any) -> None:
        result = dispatch(
            pydantic_adapter.create_author_spec,
            principal=ada,
            arguments={
                "name": "Ursula",
                "books": [
                    {"title": "The Dispossessed", "price": "9.99"},
                    {"title": "Lathe", "price": 12.5},
                ],
            },
        )
        author = Author.objects.get()
        first, second = Book.objects.all()
        assert result.service_result.get_child_change("books") == ChildCollectionChange(
            relation="books", created=(first.pk, second.pk)
        )
        assert present(pydantic_adapter.create_author_spec, result) == {
            "id": author.pk,
            "name": "Ursula",
            "books": [
                {"id": first.pk, "title": "The Dispossessed", "price": "9.99", "status": "draft"},
                {"id": second.pk, "title": "Lathe", "price": "12.50", "status": "draft"},
            ],
        }

    def test_the_output_marks_the_book_s_handle_and_label(self) -> None:
        output = pydantic_adapter.create_author_spec.output()
        assert output is not None
        books = output.get("books")
        assert books is not None and books.items is not None
        assert [(f.name, f.marking.audience) for f in books.items if f.marking] == [
            ("id", FieldAudience.HANDLE),
            ("title", FieldAudience.LABEL),
        ]


class TestWhatAModelDeclares:
    def test_the_model_declares_what_the_dataclass_declares_with_the_price_s_help(self) -> None:
        by_dataclass = DataclassValidator(declaring.AuthorIn).parameters()
        name, books = by_dataclass.get("name"), by_dataclass.get("books")
        assert books is not None and isinstance(books.items, Parameters)
        rows = Parameters(
            dataclasses.replace(p, help="In euros.") if p.name == "price" else p
            for p in books.items
        )
        expected = Parameters((name, dataclasses.replace(books, items=rows)))
        assert pydantic_adapter.create_author_spec.parameters() == expected

    def test_nothing_is_omittable_so_a_left_out_field_arrives_at_its_default(self) -> None:
        values = pydantic_adapter.PydanticValidator(pydantic_adapter.AuthorIn).validate(
            {"name": "Ursula"}, CONTEXT
        )
        assert values == {"name": "Ursula", "books": []}


class TestNames:
    def test_a_contact_takes_one_set_of_names_and_outputs_another(self) -> None:
        assert [p.name for p in pydantic_adapter.contact_validator.parameters()] == [
            "fullName",
            "mail",
        ]
        assert pydantic_adapter.contact_presenter.output().names() == ("fullName", "email")

    def test_validate_returns_the_field_names(self) -> None:
        values = pydantic_adapter.contact_validator.validate(
            {"fullName": "Ursula", "mail": "u@example.com"}, CONTEXT
        )
        assert values == {"full_name": "Ursula", "email": "u@example.com"}


class TestATree:
    def test_a_category_is_described_four_deep_then_as_objects(self) -> None:
        children = pydantic_adapter.category_validator.parameters().get("children")
        for _ in range(3):
            assert children is not None and isinstance(children.items, Parameters)
            children = children.items.get("children")
        assert children is not None
        assert children.items == "object"

    def test_a_tree_ten_deep_is_built_in_full(self) -> None:
        values = pydantic_adapter.category_validator.validate(_category(10, "leaf"), CONTEXT)
        (node,) = values["children"]
        depth = 2
        while node.children:
            (node,) = node.children
            depth += 1
        assert (depth, node.name) == (10, "leaf")

    def test_a_bad_name_ten_down_is_refused_at_its_path(self) -> None:
        with pytest.raises(InvalidArguments) as caught:
            pydantic_adapter.category_validator.validate(_category(10, None), CONTEXT)
        detail: Any = caught.value.detail
        for _ in range(9):
            detail = detail["children"][0]
        assert detail == {"name": ["Input should be a valid string"]}


@pytest.mark.django_db
class TestRefusals:
    def test_a_row_s_field_and_a_row_s_own_rule_are_addressed_by_index(self, ada: Any) -> None:
        detail = _refusal(
            {
                "name": "Ursula",
                "books": [
                    {"title": "Lathe", "price": "0"},
                    {"title": "Lathe", "price": "5", "status": "published"},
                ],
            },
            ada,
        )
        assert detail == {
            "books": {
                0: {"price": ["Input should be greater than 0"]},
                1: {"non_field_errors": ["Value error, A published book has a publication date."]},
            }
        }

    def test_a_wrong_json_type_is_refused_in_the_kernel_s_words(self, ada: Any) -> None:
        detail = _refusal({"name": 1}, ada)
        assert detail == {"name": ["Expected a string."]}
        assert "Input should be" not in str(detail)


class TestModelJsonSchema:
    def test_a_decimal_is_one_dialect_here_and_another_in_pydantic_s_schema(self) -> None:
        books = pydantic_adapter.create_author_spec.parameters().get("books")
        assert books is not None and isinstance(books.items, Parameters)
        price = books.items.get("price")
        assert price is not None
        assert (price.type, price.format) == ("string", "decimal")
        schema = pydantic_adapter.AuthorIn.model_json_schema()["$defs"]["BookIn"]
        assert {arm["type"] for arm in schema["properties"]["price"]["anyOf"]} == {
            "number",
            "string",
        }

    def test_a_bound_is_not_described_and_is_still_enforced(self) -> None:
        validator = pydantic_adapter.PydanticValidator(pydantic_adapter.BookIn)
        # A string parameter and nothing more: Parameters have no length.
        assert validator.parameters().get("title") == Parameter("title", "string", required=True)
        with pytest.raises(InvalidArguments) as caught:
            validator.validate({"title": "x" * 101, "price": Decimal(1)}, CONTEXT)
        assert caught.value.detail == {"title": ["String should have at most 100 characters"]}
