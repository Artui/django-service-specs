from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField

ID = OutputField("id", "integer")
NAME = OutputField("name", "string")


def test_is_ordered_by_declaration() -> None:
    out = Output([NAME, ID])
    assert out.fields == (NAME, ID)
    assert out.names() == ("name", "id")
    assert list(out) == [NAME, ID]
    assert len(out) == 2
    assert out.get("id") is ID
    assert out.get("missing") is None


def test_a_name_declared_twice_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"\['id'\] more than once"):
        Output((ID, OutputField("id", "string")))
