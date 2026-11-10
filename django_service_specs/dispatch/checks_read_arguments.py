from __future__ import annotations

from django_service_specs.authorization.utils import CLASS_LEVEL, SCOPE_LEVEL, declared_keywords
from django_service_specs.dispatch.utils import asks_scope_of_nothing
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def checks_read_arguments(spec: ServiceSpec | SelectorSpec | SpecSource) -> bool:
    """Whether a check of ``spec`` declares ``arguments``, asked before any row resolves."""
    spec = kernel_spec(spec)
    questions = [CLASS_LEVEL]
    if asks_scope_of_nothing(spec):
        questions.append(SCOPE_LEVEL)
    return any(
        "arguments" in declared_keywords(check, method, positional=positional)
        for check in spec.permissions or ()
        for method, positional in questions
    )
