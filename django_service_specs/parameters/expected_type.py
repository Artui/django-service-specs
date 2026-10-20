"""``expected_type`` - the refusal of a value that is not the type its parameter declares."""

from __future__ import annotations

from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage


def expected_type(json_type: str) -> CodedMessage:
    """The refusal of a value that is not ``json_type``, as one sentence a translator sees whole.

    ``"decimal"`` and ``"file"`` are the two keys that are not JSON types: the
    format arrives as a string or a number, so its refusal names both, and a
    file is a parameter's type that no JSON value is.

    One sentence per type rather than ``"Expected %(type)s"``, because an
    interpolated JSON type name would reach a translated sentence
    untranslated. The shape check and the Validators the adapters build share
    this one table, so a caller reads the same refusal whichever of them
    answered, and a transport refusing a value it read itself, such as a
    query string's, says it in the same words. Built on each call, because a
    translation looked up at import time needs configured settings before the
    package can be imported at all.

    Its code is the one DRF gives the same mistake: ``"not_a_list"`` for an
    array, as its ``ListField`` and ``ListSerializer`` both do, and
    ``"invalid"`` for everything else, as each of its scalar fields, its
    ``FileField`` and a nested ``Serializer`` handed something other than a
    mapping do. A free-form ``object`` is ``"invalid"`` too, where DRF's
    ``DictField`` would say ``"not_a_dict"``: one type here stands for both of
    its fields, and the nested serializer is the one a declared object becomes.
    """
    message = {
        "string": gettext("Expected a string."),
        "integer": gettext("Expected an integer."),
        "number": gettext("Expected a number."),
        "boolean": gettext("Expected a boolean."),
        "array": gettext("Expected an array."),
        "object": gettext("Expected an object."),
        "decimal": gettext("Expected a decimal string or a number."),
        "file": gettext("Expected a file."),
    }[json_type]
    # test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake[not-a-list]
    # holds the array's code, its [type] case everything else's.
    return CodedMessage(message, "not_a_list" if json_type == "array" else "invalid")
