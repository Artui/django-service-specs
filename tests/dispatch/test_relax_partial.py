from __future__ import annotations

import pytest
from django import forms
from django.contrib.auth.models import AnonymousUser

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.service_spec import ServiceSpec

FIELDS = Parameters.of(Parameter("fields", "array", items="string", required=True))


class _NoteForm(forms.Form):
    title = forms.CharField()


def _partial_with_a_required_shape() -> ServiceSpec:
    return ServiceSpec(
        service=lambda: None,
        permissions=[Unrestricted()],
        validator=FormValidator(_NoteForm),
        partial=True,
        shapes=FIELDS,
    )


def test_a_partial_spec_keeps_a_required_shape_required() -> None:
    """A shape selects what is presented, not what is written, so a partial
    call relaxes the Validator's fields and keeps it as declared."""
    spec = _partial_with_a_required_shape()
    relaxed = {param.name: param.required for param in relax_partial(spec, spec.parameters())}
    assert relaxed == {"fields": True, "title": False}
    assert spec_input_schema(spec)["required"] == ["fields"]


@pytest.mark.django_db
def test_dispatch_refuses_a_partial_call_that_omits_a_required_shape() -> None:
    with pytest.raises(InvalidArguments) as refused:
        dispatch(_partial_with_a_required_shape(), principal=AnonymousUser(), arguments={})
    assert set(refused.value.detail) == {"fields"}
