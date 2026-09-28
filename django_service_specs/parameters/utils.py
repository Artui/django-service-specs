"""The detail tree every refusal of arguments carries, and the helpers that build one.

[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
documents the tree's shape. These helpers exist so that everything producing
one - the shape check, ``coerce_flat``, a relation write re-rooting a row's
refusal - builds the same shape, rather than each spelling its own and a
transport learning three.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

NON_FIELD_ERRORS: Final = "non_field_errors"
"""The key a message about a node itself sits under, beside its fields' messages.

A row that is not an object has no field to hang the message on, so it goes
here inside the row: ``{"books": {1: {"non_field_errors": ["..."]}}}``. It is
Django's and DRF's spelling of the same idea, so a transport rendering either's
errors reads the kernel's without a translation table."""


def nest_detail(path: Sequence[str | int], detail: Any) -> dict[Any, Any]:
    """Root ``detail`` under ``path``: a child's refusal, addressed from its parent.

    ``nest_detail(("books", 1), {"title": ["..."]})`` is
    ``{"books": {1: {"title": ["..."]}}}``. A message list with no path left to
    hang it on is a message about the root itself, so it goes under
    ``NON_FIELD_ERRORS`` rather than making the tree a list, which
    ``InvalidArguments`` could not carry.
    """
    node = detail
    for key in reversed(path):
        node = {key: node}
    if not isinstance(node, Mapping):
        return {NON_FIELD_ERRORS: list(node)}
    return dict(node)


def merge_detail(first: Mapping[Any, Any], second: Mapping[Any, Any]) -> dict[Any, Any]:
    """One tree holding every message of both, and neither input modified.

    Where both trees reach one key, two message lists are concatenated, first's
    messages first, and two subtrees merge recursively. Where a message list
    meets a subtree - a field refused as a whole by one producer and inside by
    another - the list moves under ``NON_FIELD_ERRORS`` in the subtree, which is
    where a message about that node sits. Nothing is dropped either way: the
    point of a tree is that the caller sees every problem at once.
    """
    merged = dict(first)
    for key, value in second.items():
        merged[key] = _merge_node(merged[key], value) if key in merged else value
    return merged


def _merge_node(first: Any, second: Any) -> Any:
    # Either side may be the subtree; test_merge_detail_moves_a_message_list_meeting_a_subtree_under_non_field_errors
    # merges both ways round, which is what holds each condition.
    if isinstance(first, Mapping) or isinstance(second, Mapping):
        return merge_detail(_as_tree(first), _as_tree(second))
    return [*first, *second]


def _as_tree(node: Any) -> Mapping[Any, Any]:
    return node if isinstance(node, Mapping) else {NON_FIELD_ERRORS: node}
