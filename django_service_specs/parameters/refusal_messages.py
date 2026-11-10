from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from django_service_specs.parameters.non_field_keys import NON_FIELD_KEYS


def refusal_messages(value: Any) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every message in the refusal tree ``value``, each with its dotted path."""
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
