from __future__ import annotations

import weakref
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import rendering_selector
from django_service_specs.links.utils import required_reads
from django_service_specs.output.output import Output, OutputField
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.field_audience import FieldAudience
from django_service_specs.types.spec_link import SpecLink

# id(spec) -> (a weak reference to it, its bindings or its refusal), by identity as kernel_spec.
_BOUND: dict[int, tuple[weakref.ref[Any], dict[str, dict[str, str]] | str]] = {}


def link_bindings(spec: ServiceSpec | SelectorSpec | SpecSource) -> dict[str, dict[str, str]]:
    """Each presented affordance's ``{read: output field}``: which row field fills which read.

    Read off the selector ``spec`` presents through, as
    [`row_affordance_answers`][django_service_specs.affordances.row_affordance_answers.row_affordance_answers]
    reads it, against what ``spec`` outputs. A read binds to the field its
    [`SpecLink`][django_service_specs.types.spec_link.SpecLink] names, else to
    the visible output field of its name, else, when one required read is
    left and one field is marked ``HANDLE``, to that field. A spec with no
    output binds only what its links name. A required read is one the shape
    check demands of a caller
    ([`provider_reached`][django_service_specs.dispatch.provider_reached.provider_reached]).
    Answered once per spec and kept, refusal and all, since an output never
    changes; so a link no ``check_links`` saw is refused at its first use,
    with the same message. An exception ``output()`` raises is not kept, so a
    presenter that answers once the apps are loaded binds then.

    Raises:
        ImproperlyConfigured: a link leaves a required read unbound, matches
            more than one ``HANDLE`` field, or names a field the output does not
            declare or marks ``HIDDEN``. Every problem is named in one message.
    """
    kernel = kernel_spec(spec)
    held = _BOUND.get(id(kernel))
    if held is None:
        key = id(kernel)
        held = (weakref.ref(kernel, lambda _dead: _BOUND.pop(key, None)), _bind_all(kernel))
        _BOUND[key] = held
    bound = held[1]
    if isinstance(bound, str):
        raise ImproperlyConfigured(bound)
    return {name: dict(arguments) for name, arguments in bound.items()}


def _bind_all(kernel: ServiceSpec | SelectorSpec) -> dict[str, dict[str, str]] | str:
    """The bindings, or the refusal's message; ``output()`` raising is raised, never kept."""
    selector = rendering_selector(kernel)
    affordances = selector.affordances if selector is not None else None
    if not affordances:
        return {}
    output = kernel.output()
    problems: list[str] = []
    bound = {
        name: _bind(name, declared, output, problems) for name, declared in affordances.items()
    }
    return " ".join(problems) if problems else bound


def _bind(
    name: str, declared: AffordanceDeclarer, output: Output | None, problems: list[str]
) -> dict[str, str]:
    """One link's ``{read: field}``, appending to ``problems`` what refuses it."""
    link = declared if isinstance(declared, SpecLink) else SpecLink(declared)
    where = f"SelectorSpec.affordances[{name!r}]"
    required = required_reads(link)
    optional = tuple(read for read in link.link_reads() if read not in required)
    fields = {f.name: f for f in output} if output is not None else None
    arguments = dict(link.arguments)
    for read, field_name in arguments.items():
        if fields is None:
            continue
        found = fields.get(field_name)
        if found is None:
            problems.append(
                f"{where} binds {read!r} to {field_name!r}, which the output does not declare; "
                f"it declares {list(fields)}."
            )
        elif _hidden(found):
            problems.append(
                f"{where} binds {read!r} to {field_name!r}, which the output marks HIDDEN. A "
                "link's arguments reach its caller, and a hidden field is plumbing."
            )
    visible = {n: f for n, f in (fields or {}).items() if not _hidden(f)}
    for read in (*required, *optional):
        if read not in arguments and read in visible:
            arguments[read] = read
    unbound = [read for read in required if read not in arguments]
    if len(unbound) == 1:
        handles = [n for n, f in visible.items() if _audience(f) is FieldAudience.HANDLE]
        if len(handles) == 1:
            arguments[unbound.pop()] = handles[0]
        elif handles:
            problems.append(
                f"{where} leaves {unbound[0]!r} to the output's HANDLE field, and it marks "
                f"{handles}. Name one: SpecLink(spec, arguments={{{unbound[0]!r}: ...}})."
            )
            unbound = []
    if unbound:
        reason = (
            "no output field is named for them or marked HANDLE"
            if fields is not None
            else "the spec declares no output, so only SpecLink arguments bind"
        )
        problems.append(
            f"{where} leads to a spec requiring {unbound}, and {reason}. Bind them: "
            "SpecLink(spec, arguments={read: field})."
        )
    return {read: arguments[read] for read in (*required, *optional) if read in arguments}


def _audience(field: OutputField) -> FieldAudience | None:
    return field.marking.audience if field.marking is not None else None


def _hidden(field: OutputField) -> bool:
    return _audience(field) is FieldAudience.HIDDEN
