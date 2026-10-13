"""Rows for the mutation tests that write a file field; ``media`` is in ``conftest.py``."""

from __future__ import annotations

from django.core.files.base import ContentFile

from tests.adapter_app.models import Document

# Where ``stored_document`` puts its optional file, under the field's ``upload_to``.
STORED = "documents/notes.txt"


def stored_document(*, attachment: bool = True) -> Document:
    """A saved row holding its required file and, unless told not to, its optional one."""
    row = Document(title="Notes")
    if attachment:
        row.attachment.save("notes.txt", ContentFile(b"notes"), save=False)
    row.scan.save("scan.txt", ContentFile(b"scan"), save=False)
    row.save()
    return row


def stored_name(row: Document, field: str = "attachment") -> str:
    """A file's name as the database holds it, rather than as the instance does."""
    return Document.objects.values_list(field, flat=True).get(pk=row.pk)
