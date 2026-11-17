from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser

from django_service_specs import check_call, check_links, row_links
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import NOT_ARCHIVED, OPEN, Record
from tests.links.links import PK, TENANT, declining, listing, needs_pk, target, tenant_of, untyped


def linked(kwargs: Any) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=OPEN,
        affordances=[NOT_ARCHIVED],
        instance_selector_spec=target(PK, TENANT, kwargs=kwargs),
    )


@pytest.mark.parametrize(
    "kwargs",
    [tenant_of, declining, untyped, needs_pk],
    ids=["typed-filled", "declinable", "untyped", "untyped-requires-a-keyword"],
)
def test_a_link_the_check_passes_serves_arguments_the_shape_check_accepts(kwargs: Any) -> None:
    spec = linked(kwargs)
    notes = listing({"go": spec})
    registry = SpecRegistry()
    registry.register("notes", notes)
    registry.register("go", spec)
    assert check_links(registry) == []
    item = {"id": 7, "title": "t", "owner_id": 1, "affordances": {"go": {"available": True}}}
    arguments = row_links(notes, item)["go"]["arguments"]
    check_call(spec, principal=AnonymousUser(), arguments=arguments)
