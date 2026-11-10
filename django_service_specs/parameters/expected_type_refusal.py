from __future__ import annotations

from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage


def expected_type_refusal(kind: str) -> CodedMessage:
    """The refusal of a value that is not of ``kind``, as one sentence a translator sees whole."""
    message = {
        "string": gettext("Expected a string."),
        "integer": gettext("Expected an integer."),
        "number": gettext("Expected a number."),
        "boolean": gettext("Expected a boolean."),
        "array": gettext("Expected an array."),
        "object": gettext("Expected an object."),
        "decimal": gettext("Expected a decimal string or a number."),
        "file": gettext("Expected a file."),
    }[kind]
    return CodedMessage(message, "not_a_list" if kind == "array" else "invalid")
