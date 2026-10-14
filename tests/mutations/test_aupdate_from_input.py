"""Tests for aupdate_from_input."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.types.unset import UNSET
from tests.adapter_app.models import Document
from tests.mutations.utils import (
    STORED,
    attachment_at_the_root,
    stored_document,
    stored_name,
    stored_photo,
    stored_photo_columns,
)
from tests.relations_app.models import Author, Post, Tag, Timestamped


@pytest.mark.django_db(transaction=True)
class TestAUpdateFromInput:
    async def test_no_changes(self) -> None:
        author = await Author.objects.acreate(name="same")
        result = await aupdate_from_input(author, {"name": "same"})
        assert result.changed_fields == ()

    async def test_changes_persisted(self) -> None:
        author = await Author.objects.acreate(name="orig")
        result = await aupdate_from_input(author, {"name": "new"})
        await author.arefresh_from_db()
        assert author.name == "new"
        assert result.changed_fields == ("name",)

    async def test_unset_value_skipped(self) -> None:
        post = await Post.objects.acreate(title="orig", body="body")
        await aupdate_from_input(post, {"title": UNSET, "body": "new"})
        await post.arefresh_from_db()
        assert post.title == "orig"
        assert post.body == "new"

    async def test_field_map(self) -> None:
        post = await Post.objects.acreate(title="orig")
        await aupdate_from_input(
            post,
            {"headline": "renamed"},
            field_map={"headline": "title"},
        )
        await post.arefresh_from_db()
        assert post.title == "renamed"

    async def test_exclude_fields(self) -> None:
        post = await Post.objects.acreate(title="orig", body="b")
        await aupdate_from_input(
            post,
            {"title": "new", "body": "ignored"},
            exclude_fields=["body"],
        )
        await post.arefresh_from_db()
        assert post.title == "new"
        assert post.body == "b"

    async def test_save_called_with_update_fields(self) -> None:
        post = await Post.objects.acreate(title="orig", body="b")
        with patch.object(Post, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(post, {"title": "x", "body": "b"})
            assert mock_save.called
            assert mock_save.call_args.kwargs == {"update_fields": ["title"]}

    async def test_save_skipped_when_no_changes(self) -> None:
        post = await Post.objects.acreate(title="orig")
        with patch.object(Post, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(post, {"title": "orig"})
            assert mock_save.called is False

    async def test_full_asave_when_update_fields_false(self) -> None:
        post = await Post.objects.acreate(title="orig")
        with patch.object(Post, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(post, {"title": "orig"}, update_fields=False)
            assert mock_save.called
            assert mock_save.call_args.kwargs == {}

    async def test_explicit_update_fields_list(self) -> None:
        post = await Post.objects.acreate(title="orig", body="b")
        with patch.object(Post, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(
                post,
                {"title": "x"},
                update_fields=["title", "body"],
            )
            assert mock_save.call_args.kwargs == {"update_fields": ["title", "body"]}

    async def test_m2m_change_detected(self) -> None:
        red = await Tag.objects.acreate(name="red")
        blue = await Tag.objects.acreate(name="blue")
        post = await Post.objects.acreate(title="t")
        await post.tags.aset([red])

        result = await aupdate_from_input(post, None, m2m={"tags": [blue]})
        pks = {pk async for pk in post.tags.values_list("pk", flat=True)}
        assert pks == {blue.pk}
        assert "tags" in result.changed_fields

    async def test_m2m_no_change_when_same_set(self) -> None:
        red = await Tag.objects.acreate(name="red")
        post = await Post.objects.acreate(title="t")
        await post.tags.aset([red])

        result = await aupdate_from_input(post, None, m2m={"tags": [red]})
        assert result.changed_fields == ()

    async def test_auto_now_field_included_in_update_fields(self) -> None:
        obj = await Timestamped.objects.acreate(title="orig")
        with patch.object(Timestamped, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(obj, {"title": "new"})
            kwargs = mock_save.call_args.kwargs
            assert "updated_at" in kwargs["update_fields"]
            assert "title" in kwargs["update_fields"]

    async def test_auto_now_add_field_not_included_in_update_fields(self) -> None:
        obj = await Timestamped.objects.acreate(title="orig")
        with patch.object(Timestamped, "asave", new_callable=AsyncMock) as mock_save:
            await aupdate_from_input(obj, {"title": "new"})
            assert "created_at" not in mock_save.call_args.kwargs["update_fields"]

    async def test_auto_now_field_actually_updated_in_db(self) -> None:
        obj = await Timestamped.objects.acreate(title="orig")
        old_ts = timezone.now() - timedelta(hours=1)
        await Timestamped.objects.filter(pk=obj.pk).aupdate(updated_at=old_ts)
        await obj.arefresh_from_db()

        await aupdate_from_input(obj, {"title": "new"})
        await obj.arefresh_from_db()
        assert obj.updated_at > old_ts


@pytest.mark.django_db(transaction=True)
class TestFileFields:
    """As ``update_from_input``: ``None`` keeps a file, ``False`` clears it."""

    async def test_false_clears_the_file_and_reports_the_name_it_held(self, media: str) -> None:
        row = await sync_to_async(stored_document)()
        result = await aupdate_from_input(row, {"attachment": False})
        assert await sync_to_async(stored_name)(row) == ""
        change = result.get_field_change("attachment")
        assert change is not None
        assert (change.old, change.new) == (STORED, "")

    async def test_none_keeps_the_file_and_an_upload_replaces_it(self, media: str) -> None:
        row = await sync_to_async(stored_document)()
        kept = await aupdate_from_input(row, {"attachment": None})
        assert kept.changes == ()
        assert await sync_to_async(stored_name)(row) == STORED
        upload = SimpleUploadedFile("new.txt", b"new")
        replaced = await aupdate_from_input(row, {"attachment": upload})
        assert replaced.changed_fields == ("attachment",)
        assert await sync_to_async(stored_name)(row) == "documents/new.txt"

    async def test_an_upload_named_as_the_held_file_replaces_it(self, media: str) -> None:
        with attachment_at_the_root():
            row = await sync_to_async(stored_document)()
            assert row.attachment.name == "notes.txt"
            upload = SimpleUploadedFile("notes.txt", b"new")
            result = await aupdate_from_input(row, {"attachment": upload})
        assert result.changed_fields == ("attachment",)
        assert result.get_field_change("attachment").old == "notes.txt"
        stored = await Document.objects.aget(pk=row.pk)
        with stored.attachment.open("rb") as written:
            assert written.read() == b"new"

    async def test_the_held_file_handed_back_is_no_change(self, media: str) -> None:
        row = await sync_to_async(stored_document)()
        with patch.object(Document, "asave") as asave:
            result = await aupdate_from_input(row, {"attachment": row.attachment})
        assert result.changes == ()
        asave.assert_not_called()

    async def test_a_file_is_written_through_its_field_s_save_form_data(self, media: str) -> None:
        # As a ModelForm writes it, so a field overriding how it stores a file is honoured.
        row = await sync_to_async(stored_document)()
        attachment = Document._meta.get_field("attachment")
        with patch.object(attachment, "save_form_data") as save_form_data:
            await aupdate_from_input(row, {"attachment": False, "title": "New"})
        save_form_data.assert_called_once_with(row, "")
        assert row.title == "New"


@pytest.mark.django_db(transaction=True)
class TestImageDimensions:
    """As ``update_from_input``: an image's dimension columns are saved with it."""

    async def test_clearing_an_image_clears_its_stored_dimensions(self) -> None:
        row = await sync_to_async(stored_photo)()
        await aupdate_from_input(row, {"image": False})
        assert await sync_to_async(stored_photo_columns)(row) == {
            "image": "",
            "w": None,
            "h": None,
            "thumbnail": "thumbnails/x.png",
        }
