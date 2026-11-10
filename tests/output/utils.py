from __future__ import annotations

from typing import Any

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter

STATUSES = (("PENDING_REVIEW", "Awaiting review"), ("PAID", "Paid"))
PRIORITIES = ((1, "Low"), (2, "High"))
SPOKEN_STATUSES = [{"const": "Awaiting review"}, {"const": "Paid"}]
SPOKEN_PRIORITIES = [{"const": "Low"}, {"const": "High"}]

LINE = Output(
    (
        OutputField("sku", "string"),
        OutputField("internal_cost", "string", marking=FieldMarking.hidden()),
    )
)
CUSTOMER = Output(
    (
        OutputField("name", "string", marking=FieldMarking.label()),
        OutputField("secret", "string", marking=FieldMarking.hidden()),
    )
)
INVOICE = Output(
    (
        OutputField("id", "integer", marking=FieldMarking.handle()),
        OutputField("number", "string", marking=FieldMarking.label("The invoice number.")),
        OutputField("etag", "string", marking=FieldMarking.hidden()),
        OutputField("status", "string", choices=STATUSES),
        OutputField(
            "kind", "string", choices=STATUSES, marking=FieldMarking.handle("Pass to refund.")
        ),
        OutputField("tags", "array", items="string", choices=STATUSES),
        OutputField("lines", "array", items=LINE),
        OutputField("customer", "object", fields=CUSTOMER),
        OutputField("priority", "integer", choices=PRIORITIES),
        OutputField("urgency", "integer", choices=PRIORITIES, nullable=True),
        OutputField("note", "string", nullable=True, always_present=False),
    )
)

ROW: dict[str, Any] = {
    "id": 7,
    "number": "INV-1",
    "etag": "W/1",
    "status": "PENDING_REVIEW",
    "kind": "PAID",
    "tags": ["PENDING_REVIEW", "PAID"],
    "lines": [{"sku": "S1", "internal_cost": "9.99"}],
    "customer": {"name": "Ada", "secret": "x"},
    "priority": 1,
    "urgency": None,
    "note": "hi",
}

PROJECTED_ROW: dict[str, Any] = {
    "id": 7,
    "number": "INV-1",
    "status": "Awaiting review",
    "kind": "PAID",
    "tags": ["Awaiting review", "Paid"],
    "lines": [{"sku": "S1"}],
    "customer": {"name": "Ada"},
    "priority": "Low",
    "urgency": None,
    "note": "hi",
}

HANDLE_DESCRIPTION = "An opaque handle."

PROJECTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": HANDLE_DESCRIPTION},
        "number": {"type": "string", "description": "The invoice number."},
        "status": {"type": "string", "oneOf": SPOKEN_STATUSES},
        "kind": {
            "type": "string",
            "oneOf": [
                {"const": "PENDING_REVIEW", "title": "Awaiting review"},
                {"const": "PAID", "title": "Paid"},
            ],
            "description": "Pass to refund.",
        },
        "tags": {"type": "array", "items": {"type": "string", "oneOf": SPOKEN_STATUSES}},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
                "required": ["sku"],
            },
        },
        "customer": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        # The generated schema kept ``"integer"`` here and ``["integer", "null"]``
        # below beside display strings, which the projected payload then fails.
        # Restated as the type of the values the payload now carries.
        "priority": {"type": "string", "oneOf": SPOKEN_PRIORITIES},
        "urgency": {"type": ["string", "null"], "oneOf": [*SPOKEN_PRIORITIES, {"const": None}]},
        "note": {"type": ["string", "null"]},
    },
    "required": [
        "id",
        "number",
        "status",
        "kind",
        "tags",
        "lines",
        "customer",
        "priority",
        "urgency",
    ],
}


class InvoicePresenter(Presenter):
    """Declares ``INVOICE`` and presents a mapping as it is."""

    def output(self) -> Output:
        return INVOICE

    def present(self, value: Any) -> Any:
        return dict(value)
