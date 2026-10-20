"""``refusal_messages`` - every message in a refusal of arguments, each at its path."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from django_service_specs.parameters.non_field_keys import NON_FIELD_KEYS


def refusal_messages(value: Any) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every message in the refusal tree ``value``, each with its path from the root: ``books.1.title``.

    The tree ``InvalidArguments`` carries: a key is a step of the path, a
    row's index included, and a ``NON_FIELD_KEYS`` key adds none. A list is
    the tree's leaf, so its messages share the path, and only a list:
    anything else is one message whatever its type, a lazy translation
    (which is not a ``str``) included, so it is never taken apart into
    characters. Each message is rendered as a ``str``, in the tree's order.
    A message at the root has the empty path. Read by every transport that
    prints or places a refusal, so each reads one tree one way.
    """
    return _messages(value, ())


def _messages(value: Any, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], str]]:
    """``refusal_messages`` below ``value``, each path continuing ``path``."""
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield from _messages(inner, path if key in NON_FIELD_KEYS else (*path, str(key)))
    elif isinstance(value, list):
        for inner in value:
            yield from _messages(inner, path)
    else:
        yield path, str(value)
