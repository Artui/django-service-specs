"""``flat_arguments`` - a query string or a form's fields, read by the declaration."""

from __future__ import annotations

from typing import Any

from django.utils.datastructures import MultiValueDict

from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter, Parameters

_CSRF_FIELD = "csrfmiddlewaretoken"
"""The field ``{% csrf_token %}`` renders into a form: Django's, and never an argument."""

_COMMA_SEPARABLE = ("number", "integer", "boolean")
"""The element types a comma can never be part of, so ``?ids=1,2`` is two elements, not one.

A string can hold a comma, so a string array takes a value whole, unless its
format or its choices say otherwise: a decimal string never holds one, and
nor does a value its comma-free choices list. See ``_splits``."""


def flat_arguments(parameters: Parameters, source: MultiValueDict) -> dict[str, Any]:
    """A flat source as strings and lists of strings, read by ``parameters``, blanks read as absent.

    A flat source is a query string or a form's fields: Django's ``QueryDict``,
    or any ``MultiValueDict``, where every value is a string and a key may
    repeat. A transport reading one calls this, merges its route's kwargs into
    what comes back, and hands the result to
    [`coerce_flat`][django_service_specs.parameters.coerce_flat.coerce_flat],
    so every transport reading a flat wire reads it by the same rules. Nothing
    is coerced here.

    **A flat source is read by the declaration.** A parameter of type
    ``array`` takes every value its key was sent with, and anything else takes
    the last, as ``QueryDict`` reads a repeated key. **An array of numbers,
    integers, booleans or decimal strings also reads a value holding commas
    as its elements**, ``?ids=1,2`` as ``["1", "2"]`` with the space around a
    part trimmed, because a comma cannot be part of such a value and it is
    the spelling a django-filter CSV filter advertises; repeated keys and
    commas may mix. An empty part (``?ids=1,,2``) is not dropped as a blank
    element is: it is kept, for ``coerce_flat`` to refuse at its index as any
    malformed element is. A string array is split only where its choices
    hold no comma, as an ordering's do, so ``?o=title,-pk`` is
    ``["title", "-pk"]``; otherwise it is never split, since a comma is part
    of a string. **An array is read no further than one element past the
    most it takes** - its ``max_length``, or the
    ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting's default - so ``coerce_flat``
    refuses a list over it at its name as a whole, without a million commas
    becoming a million elements first; Django's
    ``DATA_UPLOAD_MAX_NUMBER_FIELDS`` counts keys, and a comma list is one.
    **A blank value is absent unless** ``""`` **is one the parameter can
    take**: a plain string can, and a number, a boolean, a date, a decimal,
    or a string whose choices leave the blank out cannot. A flat wire has no
    other spelling of "left blank", and an empty ``?count=`` or ``?since=``
    from a filter form is not a refusal to count or a malformed date. Each
    blank element of an array is read by the same rule, the whole array
    absent once nothing is left. Django's ``csrfmiddlewaretoken``, the field
    ``{% csrf_token %}`` renders into a form, is dropped: no Django transport
    takes it as an argument. A key ``parameters`` do not declare is kept as
    it is, so the closed argument set in dispatch stays the one place that
    refuses it, under the caller's policy.
    """
    raw: dict[str, Any] = {}
    for key in source:
        if key == _CSRF_FIELD:
            continue
        param = parameters.get(key)
        # One branch to coverage, so each condition is held by its own test:
        # test_an_undeclared_key_passes_through_for_the_closed_set_to_refuse
        # (the first) and test_a_scalar_takes_the_last_of_repeated_values (the
        # second, without which every declared value would become a list).
        if param is not None and param.type == "array":
            # The element's format too, which ``Parameter`` takes on an array
            # for its element alone: test_blank_elements_of_a_decimal_array_are_dropped.
            keep = _takes_blank(param.items, param, fmt=param.format)
            # The element type and its choices decide whether a value is split,
            # and _splits names the test holding each condition. A blank is
            # dropped first, so an empty part left by a stray comma is the
            # reader's malformed element rather than a blank.
            split = _splits(param)
            # Built no further than one element past the most the array takes,
            # which is still past it, so ``coerce_flat`` refuses the list at its
            # name as it would the whole: a value of a million commas is never
            # split a million times. One past rather than at it, or a list over
            # the bound would be cut to one that is accepted.
            most = max_length_in_force(param)
            values: list[str] = []
            for value in source.getlist(key):
                # One branch to coverage, each condition held by
                # test_a_flat_array_is_split_no_further_than_one_past_its_maximum:
                # [repeated-keys] the comparison, and the setting's ``None`` by
                # test_a_setting_of_none_splits_every_comma, which compares
                # nothing.
                if most is not None and len(values) > most:
                    break
                # One branch to coverage, so each condition is held by its own
                # test: test_blank_elements_of_a_non_string_array_are_dropped
                # (the blank: without it every element is dropped) and
                # test_blank_elements_of_a_string_array_are_kept (``not keep``).
                if value == "" and not keep:
                    continue
                if split:
                    # Split no further than the room left: [one-value] and
                    # [mixed] of the test above, and at the bound ``0``, which
                    # leaves the value whole and one past.
                    room = -1 if most is None else most - len(values)
                    values.extend(part.strip() for part in value.split(",", room))
                else:
                    values.append(value)
            if values:
                raw[key] = values
            continue
        value = source[key]
        # One branch to coverage, so each condition is held by its own test:
        # test_a_blank_string_is_kept (whether it takes a blank),
        # test_a_scalar_takes_the_last_of_repeated_values (the blank: without
        # it every integer is dropped), and
        # test_an_undeclared_key_passes_through_for_the_closed_set_to_refuse
        # (the declaration: an undeclared blank has no type to ask about).
        if (
            value == ""
            and param is not None
            and not _takes_blank(param.type, param, fmt=param.format)
        ):
            continue
        raw[key] = value
    return raw


def _splits(param: Parameter) -> bool:
    """Whether a comma in one of the array's values separates elements, so ``?o=a,-b`` is two.

    An element type that can never hold a comma splits, and so does a
    decimal string, which never holds one either: it is what a django-filter
    CSV number filter declares, whose spelling is ``?pks=1,2``. So does an
    array of strings whose declared choices hold none: every element must be
    one of them, so a value holding a comma can only be several, and refused
    whole it would refuse the spelling django-filter's ``OrderingFilter``
    takes, ``?o=title,-pk``. Without either, or with one choice that holds a
    comma, a string array takes each value whole, since a comma may be part
    of it. Repeated keys make a list either way, and the two may mix.

    The format is read alone, with no ``"string"`` beside it: ``Parameter``
    takes a format on an array only for a string element, and only
    ``decimal``.

    One branch to coverage per return, so each condition is held by its own
    test: test_an_array_reads_a_comma_separated_value_as_its_elements[number]
    (the types that split),
    test_a_decimal_array_reads_a_comma_separated_value_as_its_elements_exactly
    (the format), and of
    test_an_array_that_may_hold_a_comma_is_not_split,
    [no-declared-element-with-choices] (``"string"``: without it an
    undeclared element with comma-free choices would split), [string] (the
    choices declared) and [string-whose-choices-hold-a-comma] (none holds a
    comma); and
    test_an_array_reads_a_comma_separated_value_as_its_elements[string-whose-choices-hold-no-comma].
    """
    if param.items in _COMMA_SEPARABLE or param.format == "decimal":
        return True
    return (
        param.items == "string"
        and param.choices is not None
        and not any("," in str(choice) for choice in param.choices)
    )


def _takes_blank(json_type: object, param: Parameter, *, fmt: str | None = None) -> bool:
    """Whether ``""`` is a value of ``json_type`` under ``param``, so a blank is kept rather than absent.

    ``json_type`` is the parameter's own type, or an array's element type:
    ``None`` for an undeclared element, which ``coerce_flat`` leaves as the
    string it arrived as, and a ``Parameters`` for a row, which is no string.
    An ``"any"`` parameter is untyped, and an untyped read is handed what was
    sent, so its blank is kept as ``""`` as a string's is.
    A format names what a string decodes into, and no date or decimal is
    blank. ``choices`` constrain a scalar and each element of an array alike,
    so a blank they leave out is refused by the shape check rather than read
    as a choice, and here it is absent instead.

    One branch to coverage, so each condition is held by its own test:
    test_blank_elements_of_an_undeclared_element_type_are_kept (``None``),
    test_blank_elements_of_a_string_array_are_kept (``"string"``),
    test_a_blank_untyped_read_is_kept (``"any"``),
    test_a_blank_date_is_absent (the format),
    test_a_blank_the_choices_leave_out_is_absent (the choices, whole),
    test_a_blank_string_is_kept (``choices is None``), and
    test_a_blank_the_choices_name_is_kept (``"" in choices``).
    """
    return (
        (json_type is None or json_type in ("string", "any"))
        and fmt is None
        and (param.choices is None or "" in param.choices)
    )
