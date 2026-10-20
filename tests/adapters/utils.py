"""Helpers shared by the adapters' tests."""

from __future__ import annotations

from typing import Any

from django_service_specs.output.output import Output
from django_service_specs.parameters.parameters import Parameters


def agree(parameters: Parameters, output: Output) -> None:
    """Each declared parameter has an output field of the same name and type.

    What one declaration read by an adapter's Validator and by its Presenter
    owes: the same types going in and coming out, nested rows included.
    """
    for parameter in parameters:
        field = output.get(parameter.name)
        assert field is not None, parameter.name
        assert (field.type, field.format, field.nullable) == (
            parameter.type,
            parameter.format,
            parameter.nullable,
        ), parameter.name
        values = None if field.choices is None else tuple(value for value, _ in field.choices)
        assert parameter.choices == values, parameter.name
        if parameter.fields is not None:
            assert isinstance(field.fields, Output), parameter.name
            agree(parameter.fields, field.fields)
        if isinstance(parameter.items, Parameters):
            assert isinstance(field.items, Output), parameter.name
            agree(parameter.items, field.items)
        else:
            assert field.items == parameter.items, parameter.name


def line_arguments(**overrides: Any) -> dict[str, Any]:
    """Arguments for one ``Line`` row, the same for the dataclass and the pydantic model."""
    return {"sku": "A-1", "quantity": 1, "ship_to": {"city": "Oslo"}, **overrides}


def everything_arguments(**overrides: Any) -> dict[str, Any]:
    """Arguments for either adapter's ``Everything`` as a JSON wire would carry them."""
    return {
        "name": "Order",
        "count": 2,
        "ratio": 0.5,
        "active": True,
        "price": "12.50",
        "at": "2024-06-01T12:00:00+00:00",
        "on": "2024-06-01",
        "status": "draft",
        "priority": 2,
        "colour": "red",
        "mode": "fast",
        "tags": ["a", "b"],
        "address": {"city": "Oslo", "postcode": "0150"},
        "lines": [line_arguments()],
        **overrides,
    }
