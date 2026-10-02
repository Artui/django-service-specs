"""``project_payload`` - shape a presented payload for an agent audience."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_audience import FieldAudience


def project_payload(payload: Any, projection: AudienceProjection) -> Any:
    """Drop plumbing and speak choice displays, at any depth.

    Two changes, both driven by the declaration that shapes the schema in
    [`annotate_output_schema`][django_service_specs.output.annotate_output_schema.annotate_output_schema],
    so the two cannot disagree:

    - fields marked ``HIDDEN`` are **removed**. Removed rather than moved under
      some reserved key: a payload a model reads is read in full either way, so
      moving a field costs its keys again and hides nothing. What an agent must
      never use should not be there.
    - a field's choice value is replaced by its display, so a person is not
      read ``PENDING_REVIEW``. **Not** on a ``HANDLE``, which another tool
      takes as input. An array of choices is substituted member by member
      rather than looked up whole.

    A payload that is neither an object nor a list of them is returned as it
    is, and so is every key the projection has nothing to say about, including
    one a transport added beside the declared fields.

    Apply this where a payload becomes an agent's **answer**, not where it
    feeds the next step of a chain, which still needs the handles. Returns a
    new payload and never modifies ``payload``.
    """
    if projection.is_empty():
        return payload
    return _project(payload, projection)


def _project(payload: Any, projection: AudienceProjection) -> Any:
    if isinstance(payload, list):
        return [_project(item, projection) for item in payload]
    if not isinstance(payload, Mapping):
        return payload
    projected: dict[str, Any] = {}
    for key, value in payload.items():
        audience = projection.audience(key)
        if audience is FieldAudience.HIDDEN:
            continue
        child = projection.nested.get(key)
        if child is not None:
            projected[key] = _project(value, child)
        # One branch to coverage, so each condition is held by its own test:
        # test_a_handle_keeps_its_constant (the first) and
        # test_a_field_with_no_labels_is_passed_through (the second).
        elif audience is not FieldAudience.HANDLE and key in projection.choice_labels:
            projected[key] = _spoken(value, projection.choice_labels[key])
        else:
            projected[key] = value
    return projected


def _spoken(value: Any, labels: Mapping[Any, str]) -> Any:
    """The display for a presented choice, or the value unchanged.

    An array of choices presents a collection of values, and a whole-value
    lookup would hash a list and raise, so each member is substituted. One
    ``isinstance`` over four kinds, so each kind is held by its own case of
    ``test_each_member_of_a_collection_is_spoken``.

    An unrecognised value passes through: a stale row naming a choice that has
    since been removed should still be reported, not fail the call.
    """
    if isinstance(value, list | tuple | set | frozenset):
        return [labels.get(member, member) for member in value]
    return labels.get(value, value)
