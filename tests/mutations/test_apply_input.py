"""Tests for apply_input — in-memory, no DB writes."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from django_service_specs.mutations.apply_input import apply_input
from django_service_specs.types.unset import UNSET
from tests.adapter_app.models import Document
from tests.mutations.utils import STORED, attachment_at_the_root, stored_document
from tests.relations_app.models import Author, Post


@dataclass
class _PartialPost:
    title: str = ""
    body: str = ""
    views: int = 0


@pytest.mark.django_db
class TestApplyInput:
    def test_dict_data_sets_changed_attrs_in_memory(self) -> None:
        post = Post(title="orig", body="old", views=0)
        result = apply_input(post, {"title": "new", "body": "old"})
        assert post.title == "new"
        assert post.body == "old"
        assert result.changed_fields == ("title",)
        assert result.created is False
        assert result.instance is post

    def test_dataclass_data(self) -> None:
        post = Post(title="orig")
        result = apply_input(post, _PartialPost(title="changed", body="b"))
        assert post.title == "changed"
        assert result.changed_fields == ("title", "body")

    def test_object_with_dict(self) -> None:
        class _Obj:
            def __init__(self) -> None:
                self.title = "via-dict"

        post = Post(title="x")
        result = apply_input(post, _Obj())
        assert post.title == "via-dict"
        assert result.changed_fields == ("title",)

    def test_none_data_returns_no_changes(self) -> None:
        post = Post(title="x")
        result = apply_input(post, None)
        assert result.changed_fields == ()
        assert bool(result) is False

    def test_unset_value_skipped(self) -> None:
        post = Post(title="orig", body="hello")
        result = apply_input(post, {"title": UNSET, "body": "hi"})
        assert post.title == "orig"
        assert result.changed_fields == ("body",)

    def test_field_map_translates_keys(self) -> None:
        post = Post(title="orig")
        result = apply_input(
            post,
            {"headline": "renamed"},
            field_map={"headline": "title"},
        )
        assert post.title == "renamed"
        assert result.changed_fields == ("title",)

    def test_exclude_fields_skips_input_keys(self) -> None:
        post = Post(title="orig", body="b")
        result = apply_input(
            post,
            {"title": "new", "body": "new-body"},
            exclude_fields=["body"],
        )
        assert post.title == "new"
        assert post.body == "b"
        assert result.changed_fields == ("title",)

    def test_unset_default_in_dataclass_skipped(self) -> None:
        @dataclass
        class _Sparse:
            title: object = UNSET
            body: str = "set"

        post = Post(title="orig", body="orig-body")
        result = apply_input(post, _Sparse())
        assert post.title == "orig"
        assert post.body == "set"
        assert result.changed_fields == ("body",)

    def test_unsupported_data_type_raises(self) -> None:
        post = Post(title="x")
        with pytest.raises(TypeError):
            apply_input(post, 42)

    def test_no_save_called(self) -> None:
        author = Author.objects.create(name="orig")
        apply_input(author, {"name": "new"})
        author.refresh_from_db()
        assert author.name == "orig"


@pytest.mark.django_db
class TestFileFields:
    """As ``update_from_input``, in memory: ``None`` keeps a file, ``False`` clears it."""

    def test_false_clears_the_file_in_memory(self, media: str) -> None:
        row = stored_document()
        result = apply_input(row, {"attachment": False})
        assert row.attachment.name == ""
        change = result.get_field_change("attachment")
        assert change is not None
        assert (change.old, change.new) == (STORED, "")

    def test_none_keeps_the_file(self, media: str) -> None:
        row = stored_document()
        result = apply_input(row, {"attachment": None})
        assert result.changes == ()
        assert row.attachment.name == STORED

    def test_an_upload_named_as_the_held_file_is_set(self, media: str) -> None:
        with attachment_at_the_root():
            row = stored_document()
        upload = SimpleUploadedFile("notes.txt", b"new")
        result = apply_input(row, {"attachment": upload})
        assert result.changed_fields == ("attachment",)
        assert result.get_field_change("attachment").old == "notes.txt"
        # Set and not yet stored: the save that follows writes it.
        assert row.attachment.file is upload

    def test_the_held_file_handed_back_is_no_change(self, media: str) -> None:
        row = stored_document()
        held = row.attachment
        result = apply_input(row, {"attachment": held})
        assert result.changes == ()
        assert row.attachment is held

    def test_a_file_is_set_through_its_field_s_save_form_data(self, media: str) -> None:
        # As a ModelForm writes it, so a field overriding how it stores a file is honoured.
        row = stored_document()
        attachment = Document._meta.get_field("attachment")
        with patch.object(attachment, "save_form_data") as save_form_data:
            apply_input(row, {"attachment": False, "title": "New"})
        save_form_data.assert_called_once_with(row, "")
        assert row.title == "New"
