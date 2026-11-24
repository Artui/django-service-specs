from __future__ import annotations


def string_lengths(
    *, min_length: int | None = None, max_length: int | None = None
) -> dict[str, int] | None:
    """A string's lengths as the ``json_schema_extra`` a ``Parameter`` states them in.

    ``Parameter.min_length`` and ``max_length`` count an array's elements and are
    refused on any other type, so a string's lengths travel as the JSON Schema
    keywords ``minLength`` and ``maxLength``. Every Validator that projects a
    string's length states it through this, so ``constraints_not_held`` and every
    schema read one spelling. ``None`` where neither is given, which is what a
    ``Parameter`` with no ``json_schema_extra`` holds.
    """
    lengths: dict[str, int] = {}
    if min_length is not None:
        lengths["minLength"] = min_length
    if max_length is not None:
        lengths["maxLength"] = max_length
    return lengths or None
