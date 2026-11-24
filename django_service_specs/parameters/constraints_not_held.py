from __future__ import annotations

from django_service_specs.parameters.parameters import Parameter


def constraints_not_held(spec: Parameter, form: Parameter) -> tuple[str, ...]:
    """Each constraint ``form`` states that ``spec`` does not hold, one message apiece.

    For a transport that renders or reads a field through its own declaration, a
    Django form for one, while the spec's Validator is what runs: a constraint
    only the form states is never enforced, and the value it would have refused
    reaches the database. ``form`` is that declaration read as a ``Parameter``
    (``FormValidator(form_class).parameters()``), and ``spec`` the spec's own
    parameter of the same name. Empty when the spec holds everything:

    - **A string's lengths**, read from ``json_schema_extra`` as
      ``string_lengths`` states them: a ``maxLength`` the spec does not declare,
      or declares above the form's, and a ``minLength`` the spec does not
      declare, or declares below the form's.
    - **Choices**: the spec's must all be among the form's, so a value the form
      never offers is never taken. A spec with no choices under a form with some
      is refused.

    A spec tighter than the form passes. Numeric bounds are never compared:
    ``FormValidator`` declares no ``minimum`` or ``maximum``, so a
    ``PositiveIntegerField`` column's ``min_value=0`` asks nothing of the spec.
    Each message names the field, the form's value and the spec's; the caller
    raises, with its own words about where the form came from.
    """
    found: list[str] = []
    stated = form.json_schema_extra or {}
    held = spec.json_schema_extra or {}
    for keyword, words, looser in (
        ("maxLength", "a maximum length", lambda ours, theirs: ours > theirs),
        ("minLength", "a minimum length", lambda ours, theirs: ours < theirs),
    ):
        form_value = stated.get(keyword)
        if form_value is None:
            continue
        spec_value = held.get(keyword)
        if spec_value is None or looser(spec_value, form_value):
            found.append(
                f"{form.name!r}: the form states {words} of {form_value}, and the spec "
                f"declares {'none' if spec_value is None else spec_value}."
            )
    if form.choices is not None and (
        spec.choices is None or not all(choice in form.choices for choice in spec.choices)
    ):
        spelled = "none" if spec.choices is None else list(spec.choices)
        found.append(
            f"{form.name!r}: the form takes the choices {list(form.choices)}, and the spec "
            f"declares {spelled}."
        )
    return tuple(found)
