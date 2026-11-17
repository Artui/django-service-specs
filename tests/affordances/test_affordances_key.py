from __future__ import annotations

import django_service_specs
from django_service_specs.affordances import utils


def test_the_root_exports_the_key_the_kernel_presents_answers_under() -> None:
    assert django_service_specs.AFFORDANCES_KEY is utils.AFFORDANCES_KEY
    assert django_service_specs.AFFORDANCES_KEY == "affordances"
    assert "AFFORDANCES_KEY" in django_service_specs.__all__
