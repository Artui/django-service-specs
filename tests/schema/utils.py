"""Helpers the schema tests share: a presenter, the services and selectors it presents, a walk."""

from __future__ import annotations

from typing import Any

from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter
from tests.dispatch_app.models import Note


class NoteTitle(Presenter):
    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return {"title": value.title}


def write(**_: Any) -> None:
    return None


def nothing(**_: Any) -> Any:
    return Note.objects.none()


def walk(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every schema node - the root, each property, each array's items - however deep."""
    nodes = [schema]
    for prop in schema.get("properties", {}).values():
        nodes += walk(prop)
    if "items" in schema:
        nodes += walk(schema["items"])
    return nodes
