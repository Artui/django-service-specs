from __future__ import annotations

from django.db import models


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class Author(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "adapter_app"


class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_on = models.DateField(null=True)

    class Meta:
        app_label = "adapter_app"
        ordering = ("pk",)


class Document(models.Model):
    """A row with an optional file and a required one."""

    title = models.CharField(max_length=100)
    attachment = models.FileField(upload_to="documents", blank=True)
    scan = models.FileField(upload_to="scans")

    class Meta:
        app_label = "adapter_app"


class Photo(models.Model):
    """A row whose image stores its dimensions in two columns of its own."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, null=True, related_name="photos")
    image = models.ImageField(upload_to="photos", blank=True, width_field="w", height_field="h")
    w = models.PositiveIntegerField(null=True)
    h = models.PositiveIntegerField(null=True)
    thumbnail = models.ImageField(upload_to="thumbnails", blank=True)

    class Meta:
        app_label = "adapter_app"


class Edition(models.Model):
    """A printing of a book, one per number, held by a ``UniqueConstraint``."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="editions")
    number = models.PositiveIntegerField()

    class Meta:
        app_label = "adapter_app"
        constraints = [
            models.UniqueConstraint(fields=["book", "number"], name="one_edition_per_number")
        ]


class Shelf(models.Model):
    """A place two numbers name together: a row of a bookcase and a position along it."""

    row = models.IntegerField()
    position = models.IntegerField()

    class Meta:
        app_label = "adapter_app"
        unique_together = [("row", "position")]


class Placement(models.Model):
    """A book on a shelf, related to it by both of the shelf's numbers."""

    title = models.CharField(max_length=100)
    shelf_row = models.IntegerField()
    shelf_position = models.IntegerField()
    shelf = models.ForeignObject(
        Shelf,
        on_delete=models.CASCADE,
        from_fields=["shelf_row", "shelf_position"],
        to_fields=["row", "position"],
        related_name="placements",
    )

    class Meta:
        app_label = "adapter_app"
        ordering = ("pk",)
