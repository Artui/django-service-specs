"""Dataclasses the validator and presenter tests share.

Module-level on purpose: the annotations are strings under ``from __future__
import annotations``, and ``typing.get_type_hints`` resolves them against this
module's globals, which a class defined inside a test function cannot use.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET, UnsetType
from tests.adapter_app.models import Status


class Priority(models.IntegerChoices):
    LOW = 1, "Low"
    HIGH = 2, "High"


class Colour(Enum):
    RED = "red"
    BLUE = "blue"


class Answer(models.TextChoices):
    # Labels Django's own catalogue translates, so a test can see the display
    # read in the active language.
    YES = "y", gettext_lazy("Yes")
    NO = "n", gettext_lazy("No")


@dataclass
class Address:
    city: str
    postcode: str | None = None


@dataclass(kw_only=True)
class Line:
    pk: int | None = None
    sku: str
    quantity: int
    ship_to: Address


@dataclass
class Everything:
    """One field per mapped annotation, required ones first."""

    name: str
    count: int
    ratio: float
    active: bool
    price: Decimal
    at: dt.datetime
    on: dt.date
    status: Status
    priority: Priority
    colour: Colour
    mode: Literal["fast", "slow"]
    tags: list[str]
    address: Address
    lines: list[Line]
    note: str | None = None
    bio: str | None | UnsetType = UNSET
    level: int = 3
    extras: list[int] = field(default_factory=list)


@dataclass
class Range:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("The range ends before it starts.")


@dataclass
class Booking:
    nights: int

    def __post_init__(self) -> None:
        if self.nights > 30:
            raise ValidationError("A booking is at most 30 nights.")


@dataclass
class Schedule:
    ranges: list[Range]


@dataclass
class Computed:
    base: int
    doubled: int = field(init=False)

    def __post_init__(self) -> None:
        self.doubled = self.base * 2


@dataclass
class Marked:
    id: Annotated[int, FieldMarking.handle()]
    title: Annotated[str | None, FieldMarking.label()] = None
    internal: Annotated[str, FieldMarking.hidden()] | None = None
