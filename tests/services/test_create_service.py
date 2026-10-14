"""``CreateService``: the keywords it names are the ones dispatch hands a service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.services.create_service import CreateService
from django_service_specs.services.implements import implements
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, Titled, make_user
from tests.dispatch_app.models import Note


@pytest.mark.django_db
def test_a_conforming_service_receives_the_validated_input_as_data() -> None:
    ada = make_user("ada")

    @implements(CreateService[Mapping[str, Any], Note])
    def create_note(*, data: Mapping[str, Any], **extras: Any) -> Note:
        return Note.objects.create(owner=extras["user"], title=data["title"])

    spec = ServiceSpec(service=create_note, permissions=OPEN, validator=Titled())

    result = dispatch(spec, principal=ada, arguments={"title": "  Minutes "})

    assert result.value.title == "Minutes"
    assert result.value.owner == ada
