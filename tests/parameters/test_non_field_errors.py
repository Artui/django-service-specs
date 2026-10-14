from __future__ import annotations

import django_service_specs
from django_service_specs import parameters
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS


def test_it_is_django_and_drfs_spelling() -> None:
    assert NON_FIELD_ERRORS == "non_field_errors"


def test_it_is_public_from_the_subpackage_and_the_root() -> None:
    assert "NON_FIELD_ERRORS" in parameters.__all__
    assert "NON_FIELD_ERRORS" in django_service_specs.__all__
    assert django_service_specs.NON_FIELD_ERRORS is NON_FIELD_ERRORS
