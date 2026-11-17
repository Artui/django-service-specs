from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import CheckMessage, Error
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.link_bindings import link_bindings
from django_service_specs.affordances.utils import rendered_affordances
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.spec_link import SpecLink

UNBOUND_LINK: str = "django_service_specs.E001"
"""A presented affordance whose link cannot be bound to the rows' output."""

AMBIGUOUS_NAME: str = "django_service_specs.E002"
"""A link target the registry holds under more than one name."""


def check_links(
    registry: SpecRegistry,
    app_configs: Sequence[AppConfig] | None = None,
    **kwargs: Any,
) -> list[CheckMessage]:
    """The registry checked against itself: an error for each link it cannot bind or name.

    Each entry's presented affordances are bound by
    [`link_bindings`][django_service_specs.affordances.link_bindings.link_bindings],
    which reads the rows' output, and so may need the apps loaded: hence a
    check run when the project chooses, never when a spec is built. Each
    target the registry holds is named through ``name_of``; one it does not
    hold is no error, since a link to it keeps its answer. The kernel
    registers nothing: a project checks the registry its transports read,
    such as the one its per-app registries merge into, and makes it a Django
    system check in one line,
    ``checks.register(functools.partial(check_links, registry))``.
    ``app_configs`` and ``kwargs`` are the system check's, and unread.
    """
    errors: list[CheckMessage] = []
    for entry in registry:
        try:
            link_bindings(entry.spec)
        except ImproperlyConfigured as refused:
            errors.append(Error(str(refused), obj=entry.name, id=UNBOUND_LINK))
        for name, declared in (rendered_affordances(kernel_spec(entry.spec)) or {}).items():
            target = declared.spec if isinstance(declared, SpecLink) else declared
            if not isinstance(target, ServiceSpec):
                continue
            try:
                registry.name_of(target)
            except ValueError as refused:
                errors.append(
                    Error(f"affordances[{name!r}]: {refused}", obj=entry.name, id=AMBIGUOUS_NAME)
                )
    return errors
