from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models


class Note(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    title = models.CharField(max_length=100)
    archived = models.BooleanField(default=False)

    class Meta:
        app_label = "dispatch_app"
        ordering = ("pk",)


class LiveNoteManager(models.Manager["LiveNote"]):
    def get_queryset(self) -> models.QuerySet[Any]:
        return super().get_queryset().filter(archived=False)


class LiveNote(Note):
    objects = LiveNoteManager()

    class Meta:
        app_label = "dispatch_app"
        proxy = True
