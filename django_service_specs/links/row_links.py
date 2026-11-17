from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.affordances.utils import AFFORDANCES_KEY, rendered_affordances
from django_service_specs.links.link_bindings import link_bindings
from django_service_specs.links.utils import required_reads
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.spec_link import SpecLink

_MISSING: Final = object()


def row_links(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    item: Any,
    *,
    registry: SpecRegistry | None = None,
) -> dict[str, dict[str, Any]]:
    """Each presented affordance of ``item``, as a link: whether, what and how to call it.

    The answer for each name is
    [`row_affordance_answers`][django_service_specs.affordances.row_affordance_answers.row_affordance_answers]'s
    (``available``, and ``code`` and ``reason`` when it is not), plus ``spec``,
    the operation the link leads to, and ``arguments``, each read bound by
    [`link_bindings`][django_service_specs.links.link_bindings.link_bindings]
    with the item's value for its field; an optional read's field the item
    does not carry is left out. With a ``registry``, ``name`` is the target's name there, and
    absent when it holds none, so a transport that cannot name a target
    still has the answer.

    ``item`` is what ``present`` returned, before any audience projection,
    whose answers are read off its ``affordances`` key; or a row as dispatch
    handed it over, answered as ``row_affordance_answers`` answers it and its
    fields read by attribute or key. A spec that presents no affordances
    answers ``{}``.

    Raises:
        ImproperlyConfigured: as ``link_bindings`` and
            ``row_affordance_answers`` do, or the item does not carry the field
            a required read binds to - a raw row read for a field the output
            names by an alias, say.
        ValueError: ``registry`` holds a target under two names.
    """
    bound = link_bindings(spec)
    affordances = rendered_affordances(kernel_spec(spec)) or {}
    if not affordances:
        return {}
    answers = (
        item[AFFORDANCES_KEY]
        if isinstance(item, Mapping) and AFFORDANCES_KEY in item
        else row_affordance_answers(spec, item)
    )
    links: dict[str, dict[str, Any]] = {}
    for name, declared in affordances.items():
        target = declared.spec if isinstance(declared, SpecLink) else declared
        values = {read: _value(item, field) for read, field in bound[name].items()}
        missing = [
            bound[name][read] for read in required_reads(declared) if values[read] is _MISSING
        ]
        if missing:
            raise ImproperlyConfigured(
                f"SelectorSpec.affordances[{name!r}] binds a required read to {missing}, which "
                f"a {type(item).__name__} row does not carry. A raw row is read by the output "
                "field's name, so a field named by an alias or a source is read off the "
                "presented item."
            )
        link: dict[str, Any] = {
            **answers[name],
            "spec": target,
            "arguments": {read: value for read, value in values.items() if value is not _MISSING},
        }
        if registry is not None and isinstance(target, ServiceSpec):
            named = registry.name_of(target)
            if named is not None:
                link["name"] = named
        links[name] = link
    return links


def _value(item: Any, field: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, _MISSING)
    return getattr(item, field, _MISSING)
