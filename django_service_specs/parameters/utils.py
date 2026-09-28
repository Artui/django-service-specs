"""The spellings every refusal of arguments shares: a node's own message key, and a wrong type.

[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
documents the tree these go into. They live here so that everything producing
one - the shape check, ``coerce_flat``, a relation write re-rooting a row's
refusal, an adapter's Validator - spells them the same way, rather than each
its own and a transport learning several.
"""

from __future__ import annotations

from typing import Final

from django.utils.translation import gettext

NON_FIELD_ERRORS: Final = "non_field_errors"
"""The key a message about a node itself sits under, beside its fields' messages.

A row that is not an object has no field to hang the message on, so it goes
here inside the row: ``{"books": {1: {"non_field_errors": ["..."]}}}``. It is
Django's and DRF's spelling of the same idea, so a transport rendering either's
errors reads the kernel's without a translation table."""


def expected_type(json_type: str) -> str:
    """The refusal of a value that is not ``json_type``, as one sentence a translator sees whole.

    ``"decimal"`` is the one key that is not a JSON type: the format arrives as
    a string or a number, so its refusal names both.

    One sentence per type rather than ``"Expected %(type)s"``, because an
    interpolated JSON type name would reach a translated sentence
    untranslated. The shape check and the Validators the adapters build share
    this one table, so a caller reads the same refusal whichever of them
    answered. Built on each call, because a translation looked up at import
    time needs configured settings before the package can be imported at all.
    """
    return {
        "string": gettext("Expected a string."),
        "integer": gettext("Expected an integer."),
        "number": gettext("Expected a number."),
        "boolean": gettext("Expected a boolean."),
        "array": gettext("Expected an array."),
        "object": gettext("Expected an object."),
        "decimal": gettext("Expected a decimal string or a number."),
    }[json_type]
