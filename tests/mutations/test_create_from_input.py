"""Tests for create_from_input."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.types.unset import UNSET, UnsetType
from tests.adapter_app.models import Document
from tests.mutations.utils import stored_name
from tests.relations_app.models import Author, Post, Tag


@dataclass
class _PostInput:
    title: str
    body: str = "default-body"


@dataclass
class _ComputedPostInput:
    title: str
    # Computed by the dataclass and never taken, so never written either.
    views: int = field(init=False)

    def __post_init__(self) -> None:
        self.views = len(self.title) * 100


@pytest.mark.django_db
class TestCreateFromInput:
    def test_creates_persisted_instance(self) -> None:
        result = create_from_input(Author, {"name": "Ada"})
        assert result.created is True
        assert result.instance.pk is not None
        assert Author.objects.filter(name="Ada").exists()

    def test_changes_record_creation_fields(self) -> None:
        result = create_from_input(Author, {"name": "Ada"})
        assert result.changed_fields == ("name",)
        change = result.get_field_change("name")
        assert change is not None
        assert isinstance(change.old, UnsetType)
        assert change.new == "Ada"

    def test_dataclass_input(self) -> None:
        result = create_from_input(Post, _PostInput(title="hi"))
        assert result.instance.title == "hi"
        assert result.instance.body == "default-body"
        assert "title" in result.changed_fields
        assert "body" in result.changed_fields

    def test_a_field_declared_init_false_is_not_written(self) -> None:
        result = create_from_input(Post, _ComputedPostInput(title="hi"))
        result.instance.refresh_from_db()
        assert result.instance.views == 0
        assert result.changed_fields == ("title",)

    def test_unset_fields_omitted_from_create(self) -> None:
        @dataclass
        class _Sparse:
            title: str = "abc"
            body: object = UNSET

        result = create_from_input(Post, _Sparse())
        assert result.changed_fields == ("title",)
        # Default DB value used since `body` not assigned.
        assert result.instance.body == ""

    def test_field_map(self) -> None:
        result = create_from_input(
            Post,
            {"headline": "Mapped"},
            field_map={"headline": "title"},
        )
        assert result.instance.title == "Mapped"
        assert result.changed_fields == ("title",)

    def test_exclude_fields(self) -> None:
        result = create_from_input(
            Author,
            {"name": "x", "drop_me": "secret"},
            exclude_fields=["drop_me"],
        )
        assert result.instance.name == "x"
        assert result.changed_fields == ("name",)

    def test_m2m_assignment_after_save(self) -> None:
        red = Tag.objects.create(name="red")
        blue = Tag.objects.create(name="blue")
        result = create_from_input(
            Post,
            {"title": "tagged"},
            m2m={"tags": [red, blue]},
        )
        assert set(result.instance.tags.values_list("pk", flat=True)) == {red.pk, blue.pk}
        assert "tags" in result.changed_fields
        tags_change = result.get_field_change("tags")
        assert tags_change is not None
        assert isinstance(tags_change.old, UnsetType)

    def test_m2m_with_pks(self) -> None:
        red = Tag.objects.create(name="red")
        result = create_from_input(
            Post,
            {"title": "by-id"},
            m2m={"tags": [red.pk]},
        )
        assert list(result.instance.tags.values_list("pk", flat=True)) == [red.pk]

    def test_m2m_none_treated_as_empty(self) -> None:
        # Passing None for an m2m attr should set an empty relation, not error.
        result = create_from_input(
            Post,
            {"title": "no-tags"},
            m2m={"tags": None},
        )
        assert list(result.instance.tags.all()) == []
        # The change is still recorded for creates.
        assert "tags" in result.changed_fields

    def test_foreign_key_assignment(self) -> None:
        author = Author.objects.create(name="a")
        result = create_from_input(Post, {"title": "x", "author": author})
        assert result.instance.author == author


def _scan() -> SimpleUploadedFile:
    return SimpleUploadedFile("scan.txt", b"scan")


@pytest.mark.django_db
class TestFileFields:
    """A file field is written as a ``ModelForm`` writes it: ``None`` leaves it, ``False`` clears."""

    def test_false_stores_no_file(self, media: str) -> None:
        result = create_from_input(Document, {"title": "T", "attachment": False, "scan": _scan()})
        assert stored_name(result.instance) == ""
        change = result.get_field_change("attachment")
        assert change is not None
        assert change.new == ""
        assert change.new is not False

    def test_none_is_left_to_the_model(self, media: str) -> None:
        result = create_from_input(Document, {"title": "T", "attachment": None, "scan": _scan()})
        assert stored_name(result.instance) == ""
        assert result.get_field_change("attachment") is None
        assert result.changed_fields == ("title", "scan")

    def test_an_upload_is_stored(self, media: str) -> None:
        result = create_from_input(Document, {"title": "T", "scan": _scan()})
        assert Document.objects.get(pk=result.instance.pk).scan.name == "scans/scan.txt"
