"""Tests for update_from_input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import QuerySet
from django.forms import modelform_factory
from django.utils import timezone

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.unset import UNSET
from tests.adapter_app.models import Author as BookAuthor
from tests.adapter_app.models import Book, Document, Photo
from tests.dispatch.utils import OPEN, PK, make_user
from tests.mutations.utils import (
    PHOTO,
    STORED,
    attachment_at_the_root,
    stored_document,
    stored_name,
    stored_photo,
    stored_photo_columns,
)
from tests.relations_app.models import Author, Post, Tag, Timestamped


@pytest.mark.django_db
class TestUpdateFromInput:
    def test_no_changes_returns_empty_result(self) -> None:
        author = Author.objects.create(name="same")
        result = update_from_input(author, {"name": "same"})
        assert result.changed_fields == ()
        assert bool(result) is False
        assert result.created is False

    def test_changes_persisted(self) -> None:
        author = Author.objects.create(name="orig")
        result = update_from_input(author, {"name": "new"})
        author.refresh_from_db()
        assert author.name == "new"
        assert result.changed_fields == ("name",)

    def test_change_records_old_and_new(self) -> None:
        author = Author.objects.create(name="orig")
        result = update_from_input(author, {"name": "new"})
        change = result.get_field_change("name")
        assert change is not None
        assert change.old == "orig"
        assert change.new == "new"

    def test_unset_value_skipped(self) -> None:
        post = Post.objects.create(title="orig", body="body")
        result = update_from_input(post, {"title": UNSET, "body": "new-body"})
        post.refresh_from_db()
        assert post.title == "orig"
        assert post.body == "new-body"
        assert result.changed_fields == ("body",)

    def test_field_map(self) -> None:
        post = Post.objects.create(title="orig")
        result = update_from_input(
            post,
            {"headline": "renamed"},
            field_map={"headline": "title"},
        )
        post.refresh_from_db()
        assert post.title == "renamed"
        assert result.changed_fields == ("title",)

    def test_exclude_fields(self) -> None:
        post = Post.objects.create(title="orig", body="b")
        result = update_from_input(
            post,
            {"title": "new", "body": "ignored"},
            exclude_fields=["body"],
        )
        post.refresh_from_db()
        assert post.title == "new"
        assert post.body == "b"
        assert result.changed_fields == ("title",)

    def test_dataclass_input(self) -> None:
        @dataclass
        class _PartialPost:
            title: str = "fresh"
            body: object = UNSET

        post = Post.objects.create(title="orig", body="orig-body")
        result = update_from_input(post, _PartialPost())
        post.refresh_from_db()
        assert post.title == "fresh"
        assert post.body == "orig-body"
        assert result.changed_fields == ("title",)

    def test_save_only_calls_with_changed_update_fields(self) -> None:
        post = Post.objects.create(title="orig", body="b", views=1)
        with patch.object(Post, "save", autospec=True) as mock_save:
            update_from_input(post, {"title": "x", "body": "b"})
            assert mock_save.called
            kwargs = mock_save.call_args.kwargs
            assert kwargs == {"update_fields": ["title"]}

    def test_save_skipped_when_no_changes_default(self) -> None:
        post = Post.objects.create(title="orig")
        with patch.object(Post, "save", autospec=True) as mock_save:
            update_from_input(post, {"title": "orig"})
            assert mock_save.called is False

    def test_full_save_when_update_fields_false(self) -> None:
        post = Post.objects.create(title="orig")
        with patch.object(Post, "save", autospec=True) as mock_save:
            update_from_input(post, {"title": "orig"}, update_fields=False)
            assert mock_save.called
            assert mock_save.call_args.kwargs == {}

    def test_explicit_update_fields_list(self) -> None:
        post = Post.objects.create(title="orig", body="b")
        with patch.object(Post, "save", autospec=True) as mock_save:
            update_from_input(post, {"title": "x"}, update_fields=["title", "body"])
            kwargs = mock_save.call_args.kwargs
            assert kwargs == {"update_fields": ["title", "body"]}

    def test_m2m_change_detected(self) -> None:
        red = Tag.objects.create(name="red")
        blue = Tag.objects.create(name="blue")
        post = Post.objects.create(title="t")
        post.tags.set([red])

        result = update_from_input(post, None, m2m={"tags": [blue]})
        assert set(post.tags.values_list("pk", flat=True)) == {blue.pk}
        assert "tags" in result.changed_fields
        change = result.get_field_change("tags")
        assert change is not None
        assert change.old == [red.pk]

    def test_m2m_no_change_when_same_set(self) -> None:
        red = Tag.objects.create(name="red")
        post = Post.objects.create(title="t")
        post.tags.set([red])

        result = update_from_input(post, None, m2m={"tags": [red]})
        assert result.changed_fields == ()

    def test_m2m_pks_compared_against_current(self) -> None:
        red = Tag.objects.create(name="red")
        blue = Tag.objects.create(name="blue")
        post = Post.objects.create(title="t")
        post.tags.set([red])

        result = update_from_input(post, None, m2m={"tags": [red.pk, blue.pk]})
        assert set(post.tags.values_list("pk", flat=True)) == {red.pk, blue.pk}
        assert "tags" in result.changed_fields

    def test_auto_now_field_included_in_update_fields(self) -> None:
        obj = Timestamped.objects.create(title="orig")
        with patch.object(Timestamped, "save", autospec=True) as mock_save:
            update_from_input(obj, {"title": "new"})
            kwargs = mock_save.call_args.kwargs
            assert "updated_at" in kwargs["update_fields"]
            assert "title" in kwargs["update_fields"]

    def test_auto_now_add_field_not_included_in_update_fields(self) -> None:
        obj = Timestamped.objects.create(title="orig")
        with patch.object(Timestamped, "save", autospec=True) as mock_save:
            update_from_input(obj, {"title": "new"})
            assert "created_at" not in mock_save.call_args.kwargs["update_fields"]

    def test_explicit_update_fields_not_modified_by_auto_now(self) -> None:
        obj = Timestamped.objects.create(title="orig")
        with patch.object(Timestamped, "save", autospec=True) as mock_save:
            update_from_input(obj, {"title": "new"}, update_fields=["title"])
            assert mock_save.call_args.kwargs == {"update_fields": ["title"]}

    def test_auto_now_field_actually_updated_in_db(self) -> None:
        obj = Timestamped.objects.create(title="orig")
        # Force updated_at to a value one hour in the past to ensure a measurable diff.
        old_ts = timezone.now() - timedelta(hours=1)
        Timestamped.objects.filter(pk=obj.pk).update(updated_at=old_ts)
        obj.refresh_from_db()

        update_from_input(obj, {"title": "new"})
        obj.refresh_from_db()
        assert obj.updated_at > old_ts

    def test_the_new_auto_now_value_needs_no_reload_to_be_read(self) -> None:
        # Django's pre_save puts the new timestamp on the instance, so the
        # returned one already carries it. The docs draw the line between
        # values like this and the ones only a reload or a re-fetch produces
        # (an F() expression, a fetch-time annotation), so pin this end of it.
        obj = Timestamped.objects.create(title="orig")
        Timestamped.objects.filter(pk=obj.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        obj.refresh_from_db()

        result = update_from_input(obj, {"title": "new"})

        assert result.instance.updated_at == Timestamped.objects.get(pk=obj.pk).updated_at


@pytest.mark.django_db
class TestFileFields:
    """A file field is written as a ``ModelForm`` writes it: ``None`` keeps, ``False`` clears."""

    def test_false_clears_the_file_and_reports_the_name_it_held(self, media: str) -> None:
        row = stored_document()
        result = update_from_input(row, {"attachment": False})
        assert stored_name(row) == ""
        change = result.get_field_change("attachment")
        assert change is not None
        assert change.old == STORED
        # What was written, as other fields report theirs: no file, not the
        # form's marker for one.
        assert change.new == ""
        assert change.new is not False

    def test_false_on_a_row_holding_no_file_changes_nothing(self, media: str) -> None:
        row = stored_document(attachment=False)
        with patch.object(Document, "save") as save:
            result = update_from_input(row, {"attachment": False})
        assert result.changes == ()
        save.assert_not_called()

    def test_none_keeps_the_file(self, media: str) -> None:
        row = stored_document()
        result = update_from_input(row, {"attachment": None, "title": "Kept"})
        assert stored_name(row) == STORED
        assert result.changed_fields == ("title",)

    def test_an_upload_replaces_the_file(self, media: str) -> None:
        row = stored_document()
        upload = SimpleUploadedFile("new.txt", b"new")
        result = update_from_input(row, {"attachment": upload})
        assert stored_name(row) == "documents/new.txt"
        assert result.changed_fields == ("attachment",)
        with row.attachment.open("rb") as written:
            assert written.read() == b"new"

    def test_an_upload_named_as_the_held_file_replaces_it_as_a_model_form_does(
        self, media: str
    ) -> None:
        # The name says nothing about the content: an upload is a file to
        # write, whatever it is called, and a ModelForm writes it.
        with attachment_at_the_root():
            row = stored_document()
            twin = stored_document()
            assert row.attachment.name == "notes.txt"
            result = update_from_input(row, {"attachment": SimpleUploadedFile("notes.txt", b"new")})
            form = modelform_factory(Document, fields=["attachment"])(
                data={},
                files={"attachment": SimpleUploadedFile("notes.txt", b"new")},
                instance=twin,
            )
            form.save()
        for written in (row, twin):
            with Document.objects.get(pk=written.pk).attachment.open("rb") as stored:
                assert stored.read() == b"new"
        assert result.changed_fields == ("attachment",)
        # The name the row held, as a clear reports it.
        assert result.get_field_change("attachment").old == "notes.txt"

    def test_the_held_file_handed_back_is_no_change(self, media: str) -> None:
        # A file the row already holds is no upload, so it compares by name and
        # is not written again; a ModelForm's field cleans to it when nothing
        # is uploaded.
        row = stored_document()
        with patch.object(Document, "save") as save:
            result = update_from_input(row, {"attachment": row.attachment, "scan": row.scan})
        assert result.changes == ()
        save.assert_not_called()

    def test_an_upload_fills_a_field_holding_no_file(self, media: str) -> None:
        row = stored_document(attachment=False)
        result = update_from_input(row, {"attachment": SimpleUploadedFile("new.txt", b"new")})
        assert stored_name(row) == "documents/new.txt"
        assert result.changed_fields == ("attachment",)

    def test_a_file_is_written_through_its_field_s_save_form_data(self, media: str) -> None:
        # As a ModelForm writes it, so a field overriding how it stores a file is honoured.
        row = stored_document()
        attachment = Document._meta.get_field("attachment")
        with patch.object(attachment, "save_form_data") as save_form_data:
            update_from_input(row, {"attachment": False, "title": "New"})
        save_form_data.assert_called_once_with(row, "")
        assert row.title == "New"

    def test_none_and_false_on_any_other_field_are_written_as_they_came(self) -> None:
        # Only a file field reads ``None`` as keep and ``False`` as no file.
        post = Post.objects.create(title="t", published=True, author=Author.objects.create())
        result = update_from_input(post, {"published": False, "author": None})
        post.refresh_from_db()
        assert (post.published, post.author) == (False, None)
        assert result.changed_fields == ("published", "author")
        assert result.get_field_change("published").new is False


@pytest.mark.django_db
class TestImageDimensions:
    """An image's dimension columns are saved with it, as a ``ModelForm`` saves them."""

    def test_clearing_an_image_clears_its_stored_dimensions_as_a_model_form_does(self) -> None:
        row = stored_photo()
        twin = stored_photo()
        result = update_from_input(row, {"image": False})
        modelform_factory(Photo, fields=["image"])(data={"image-clear": "on"}, instance=twin).save()
        expected = {"image": "", "w": None, "h": None, "thumbnail": "thumbnails/x.png"}
        assert stored_photo_columns(row) == expected
        assert stored_photo_columns(twin) == expected
        # The dimensions are derived, so the change reported is the image's alone.
        assert result.changed_fields == ("image",)

    def test_replacing_an_image_stores_the_new_one_s_dimensions(self, media: str) -> None:
        row = stored_photo()
        upload = SimpleUploadedFile("y.png", b"not read: the dimensions are patched")
        with patch("django.core.files.images.get_image_dimensions", return_value=(30, 40)):
            update_from_input(row, {"image": upload})
        columns = stored_photo_columns(row)
        assert (columns["image"], columns["w"], columns["h"]) == ("photos/y.png", 30, 40)

    def test_an_image_with_no_dimension_columns_saves_only_itself(self) -> None:
        row = stored_photo()
        with patch.object(Photo, "save") as save:
            update_from_input(row, {"thumbnail": False})
        save.assert_called_once_with(update_fields=["thumbnail"])

    def test_an_image_left_alone_saves_none_of_its_dimensions(self) -> None:
        row = stored_photo()
        with patch.object(Photo, "save") as save:
            update_from_input(row, {"thumbnail": False, "image": None})
        save.assert_called_once_with(update_fields=["thumbnail"])

    def test_an_explicit_list_is_saved_as_given(self) -> None:
        row = stored_photo()
        with patch.object(Photo, "save") as save:
            update_from_input(row, {"image": False}, update_fields=["image"])
        save.assert_called_once_with(update_fields=["image"])

    def test_a_nested_row_s_image_is_cleared_with_its_dimensions(self) -> None:
        book = Book.objects.create(author=BookAuthor.objects.create(name="a"), title="t", price=1)
        photo = stored_photo(book=book)
        assert stored_photo_columns(photo)["image"] == PHOTO
        update_from_input(
            book,
            {"photos": [{"pk": photo.pk, "image": False}]},
            relations={"photos": ChildSpec(model=Photo, fk="book")},
        )
        assert stored_photo_columns(photo) == {
            "image": "",
            "w": None,
            "h": None,
            "thumbnail": "thumbnails/x.png",
        }


class _DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "attachment", "scan"]


def _document_by_pk(*, pk: int) -> QuerySet[Document]:
    return Document.objects.filter(pk=pk)


def _update(*, instance: Document, data: dict[str, Any], **pool: Any) -> ChangeResult[Document]:
    return update_from_input(instance, data)


@pytest.mark.django_db
class TestAFormsClearThroughDispatch:
    """A partial update validated by the form, written by ``update_from_input``."""

    @staticmethod
    def _run(row: Document, arguments: dict[str, Any]) -> ChangeResult[Document]:
        spec = ServiceSpec(
            service=_update,
            permissions=OPEN,
            validator=FormValidator(_DocumentForm),
            partial=True,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=_document_by_pk, reads=PK
            ),
        )
        result = dispatch(spec, principal=make_user("ada"), arguments={"pk": row.pk, **arguments})
        return result.value

    def test_the_checked_box_clears_the_file(self, media: str) -> None:
        row = stored_document()
        changed = self._run(row, {"attachment-clear": True})
        assert stored_name(row) == ""
        assert changed.changed_fields == ("attachment",)

    def test_an_upload_replaces_it(self, media: str) -> None:
        row = stored_document()
        self._run(row, {"attachment": SimpleUploadedFile("new.txt", b"new")})
        assert stored_name(row) == "documents/new.txt"

    @pytest.mark.parametrize(
        "arguments",
        [{}, {"attachment": None}, {"attachment-clear": False}],
        ids=["absent", "null", "unchecked"],
    )
    def test_anything_else_keeps_it(self, media: str, arguments: dict[str, Any]) -> None:
        row = stored_document()
        changed = self._run(row, {"title": "Kept", **arguments})
        assert stored_name(row) == STORED
        assert changed.changed_fields == ("title",)
