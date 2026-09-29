"""Models the pydantic validator and presenter tests share.

Module-level on purpose: the annotations are strings under ``from __future__
import annotations``, and pydantic resolves them against this module's
globals. ``Everything`` mirrors the dataclass tests' model of the same name,
field for field, so the two adapters can be compared on one declaration.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from django_service_specs.output.field_marking import FieldMarking
from tests.adapter_app.models import Status
from tests.adapters.dataclass.utils import Answer, Colour, Priority

__all__ = ["Answer", "Colour", "Priority"]


class Address(BaseModel):
    city: str
    postcode: str | None = None


class Line(BaseModel):
    pk: int | None = None
    sku: str
    quantity: int
    ship_to: Address


class Everything(BaseModel):
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
    level: int = 3
    extras: list[int] = Field(default_factory=list)


class Range(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def _ordered(self) -> Range:
        if self.end < self.start:
            raise ValueError("The range ends before it starts.")
        return self


class Schedule(BaseModel):
    ranges: list[Range]
    first: Range | None = None


class Node(BaseModel):
    """A tree: the self-referential shape the appearance bound exists for."""

    name: str
    children: list[Node] = []


class Leaf(BaseModel):
    label: str


class Leaves(BaseModel):
    """One model five times, each on its own path: none of them is truncated."""

    a: Leaf
    b: Leaf
    c: Leaf
    d: Leaf
    e: Leaf


class Marked(BaseModel):
    id: Annotated[int, FieldMarking.handle()]
    title: Annotated[str | None, FieldMarking.label()] = None
    internal: Annotated[str, FieldMarking.hidden()] | None = None


class Priced(BaseModel):
    net: Decimal
    rate: Decimal = Decimal("0.25")
    secret: str = Field("x", exclude=True)

    @computed_field
    @property
    def gross(self) -> Decimal:
        return self.net * (1 + self.rate)
