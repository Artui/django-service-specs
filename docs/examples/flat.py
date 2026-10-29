"""Reading a flat source: a filter form's query string, read, merged and coerced."""

from __future__ import annotations

from typing import Any

from django.http import QueryDict

# --8<-- [start:read]
from django_service_specs import (
    Parameter,
    Parameters,
    check_arguments,
    coerce_flat,
    flat_arguments,
)

NOTES = Parameters.of(
    Parameter("project", "integer"),
    Parameter("search", "string"),
    Parameter("since", "string", format="date"),
    Parameter("ids", "array", items="integer"),
    Parameter("o", "array", items="string", choices=("title", "-title", "pk", "-pk")),
)


def arguments(query: QueryDict, route: dict[str, str]) -> dict[str, Any]:
    read = flat_arguments(NOTES, query)
    return check_arguments(NOTES, coerce_flat(NOTES, {**read, **route}))


# A filter form submitted with its date left blank, and a route capturing the project.
QUERY = QueryDict("search=&since=&ids=3,5&ids=8&o=title,-pk&csrfmiddlewaretoken=t0k3n")
ROUTE = {"project": "4"}

READ = {"search": "", "ids": ["3", "5", "8"], "o": ["title", "-pk"]}
TYPED = {"project": 4, "search": "", "ids": [3, 5, 8], "o": ["title", "-pk"]}
# --8<-- [end:read]
