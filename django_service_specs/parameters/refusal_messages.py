"""``refusal_messages`` - every message in a refusal of arguments, each at its path."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from django_service_specs.parameters.non_field_keys import NON_FIELD_KEYS


def refusal_messages(
    value: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every message below ``value``, each with its path from where the walk began: ``books.1.title``.

    The tree ``InvalidArguments`` carries: a row's index is a step of the path,
    and a ``NON_FIELD_KEYS`` key adds none. A list is the tree's leaf, so its
    messages share the path, and only a list: anything else is one message
    whatever its type, a lazy translation (which is not a ``str``) included, so
    it is never taken apart into characters. Read by every transport that
    prints or places a refusal, so each reads one tree one way.
    """
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield from refusal_messages(inner, path if key in NON_FIELD_KEYS else (*path, str(key)))
    elif isinstance(value, list):
        for inner in value:
            yield from refusal_messages(inner, path)
    else:
        yield path, str(value)
