from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.validation.validator_parameters import validator_parameters


def route_captures(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    captured: Iterable[str],
    *,
    mapped: Mapping[str, str | None] | None = None,
    call_context: dict[str, Any] | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Of the names a route ``captured``, those that are arguments, and those that are namesakes.

    For an HTTP edge merging a URL's captures into a call: it hands the names
    (``view.kwargs`` itself will do, read for its keys) and merges only the
    first set. A capture holds a URL converter's ``to_python()`` output, while
    a Validator field reads what the caller sent, so the two cannot share a
    value. Of the names:

    - **the first set** is every capture naming a top-level parameter
      ``spec`` declares that is no Validator field: a read, the target
      selector's reads, a shape. Each is an argument
      (test_a_capture_naming_a_declared_parameter_is_an_argument);
    - **the second set** is every capture named like a field of the spec's
      Validator, a namesake. It is no argument: the field stays the
      caller's, sent in the body, and a target selector wanting the route's
      value reads ``view.kwargs`` through its ``kwargs`` provider, as a
      provider's key named like a field is a namesake in
      [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
      (test_the_capture_rule_names_what_the_provider_rule_names). A read and
      a field never share a name, so the split is clean; on a ``many`` spec
      the fields are each row's, and a read of a row field's name wins
      (test_a_many_spec_s_read_wins_over_a_row_field_of_its_name);
    - a capture in neither set names nothing ``spec`` declares, and each edge
      keeps its own rule for it: dropped, or refused as the host's
      misconfiguration.

    A capture naming a ``many`` spec's list is refused, since the list is
    the caller's body. ``mapped`` is an edge's own renaming of its captures,
    capture to target, ``None`` dropping one: a target that is a Validator
    field is refused, naming the capture and the field, whatever the route
    captured, since no rename can make a URL value the caller's
    (test_an_identity_mapping_onto_a_field_is_refused_whatever_the_route_captured).
    The edge hands it where it checks its own configuration, and ``captured``
    under the names it fills. ``call_context`` reaches the Validator as in
    [`provider_reached`][django_service_specs.dispatch.provider_reached.provider_reached]:
    the call's dict during a call, ``None`` outside one.

    Only a service spec with a Validator has namesakes, each conjunct held by
    its own test: a selector spec has no Validator
    (test_a_selector_spec_has_no_namesake), and a service spec may have none
    (test_a_service_spec_with_no_validator_has_no_namesake).

    Raises:
        ImproperlyConfigured: a capture names a ``many`` spec's list, or
            ``mapped`` maps a capture onto a Validator field.
    """
    spec = kernel_spec(spec)
    names = frozenset(captured)
    declared = spec.parameters(call_context=call_context).names()
    fields: frozenset[str] = frozenset()
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        fields = validator_parameters(spec.validator, call_context=call_context).names()
        if spec.many:
            fields -= declared
            _refuse_the_list(spec, names)
    _refuse_mapped_fields(mapped or {}, fields)
    return names & (declared - fields), names & fields


def _refuse_the_list(spec: ServiceSpec, names: frozenset[str]) -> None:
    if spec.many_argument in names:
        raise ImproperlyConfigured(
            f"The route captures {spec.many_argument}, the caller's list on a many spec. "
            "Rename the capture, or set many_argument to another name."
        )


def _refuse_mapped_fields(mapped: Mapping[str, str | None], fields: frozenset[str]) -> None:
    onto = sorted((capture, target) for capture, target in mapped.items() if target in fields)
    if onto:
        pairs = ", ".join(f"the capture {capture} onto {target}" for capture, target in onto)
        raise ImproperlyConfigured(
            f"The route maps {pairs}, a Validator field. A field is the caller's, never a "
            "route's: map the capture to a read, or to None to drop it."
        )
