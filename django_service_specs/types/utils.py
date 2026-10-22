"""Helpers shared across ``types/``, with every reader of an affordance, and between a declaration and its schema.

They live here rather than in ``affordances/`` for the reason ``types/`` exists.
``Affordance`` and ``ServiceSpec`` both need them at construction, and
``affordances/`` imports ``specs/``, so a home there would make the first spec
to load pull in the phase that imports it back, half-initialized. The schema
keywords and ``is_json_native`` are here for the same reason: ``Parameter`` and
``OutputField`` read them at construction, and ``schema/`` imports both
declarations, so a home there would be an import ring. Nothing here imports
anything else in the package.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

# The pool names dispatch seeds per call rather than per process: the validated
# input (``data``), the resolved target (``instance``, ``collection``), and the
# values only a later step has - the service's return, as ``result`` and
# ``instance`` in an output selector's pool, and the queryset being shaped, as
# ``queryset`` in ``extend_queryset``'s. An affordance condition reading one of them is a rule
# about *this call*, and could never be answered without attempting the call,
# which is the one thing an affordance exists to allow. The declaration refuses
# a callable naming them, and ``ambient_pool`` withholds them from one that takes
# ``**kwargs``, so the two cannot disagree about what a condition may see.
#
# Written out rather than derived from ``RESERVED_POOL_SEEDS``, because ``types/``
# imports nothing else in the package. The rest of the reserved names - ``user``
# and ``progress`` - are ambient, and ``tests/types/test_utils.py`` holds the
# partition, so a name reserved later has to be placed on one side of it.
#
# ``serializer`` is djangorestframework-services' per-call name for the bound
# input serializer, which this kernel never seeds. It stays here because that
# package re-exports these functions in place of its own, and hands them a pool
# with ``serializer`` in it and a reserved set naming it: without it, a condition
# taking ``**kwargs`` would be handed the call's input there.
PER_CALL_POOL_NAMES: Final = frozenset(
    {"data", "instance", "collection", "result", "queryset", "serializer"}
)


def is_row_condition(when: Any) -> bool:
    """True when an affordance's ``when`` is an ORM expression - a condition on the row.

    ``resolve_expression`` is the protocol every ORM expression and ``Q``
    implements and no plain callable does, so it separates the two shapes
    without importing each expression class. Shared because the declaration,
    the enforcement and the list projection must all draw the line in the same
    place: a condition one of them treats as a callable and another as SQL is
    two definitions of one rule.
    """
    return hasattr(when, "resolve_expression")


def affordance_alias(name: str, code: str) -> str:
    """The annotation a row carries one affordance's answer under.

    ``name`` is the key a ``SelectorSpec.affordances`` entry is declared under and
    ``code`` the affordance's own. Prefixed and double-underscored on purpose: a
    Django field name may not contain ``__``, so the alias can never shadow a
    model field, and the prefix keeps it clear of a model *method* of the same
    name, which ``annotate`` would silently overwrite on every instance.
    """
    return f"affordance__{name}__{code}"


def is_json_native(value: Any) -> bool:
    """Whether ``value`` survives the JSON encoding every transport performs on a schema.

    A schema carries a value in three places, a ``default``, a choice and a
    ``json_schema_extra``, and each reaches the wire as it is. A ``Decimal``, a
    date, a lazy translation or a model row there does not describe the input
    less well - it breaks the encoding, so the transport fails to list the
    operation at all. The emitters leave such a default or choice out rather
    than restate it in a form the declaration did not choose, and a
    declaration refuses such an extra where it is written.

    ``bool`` needs no case of its own: it is an ``int``, and both are native.
    """
    if value is None or isinstance(value, (str, int, float)):
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_native(item) for key, item in value.items())
    return False


# The keywords a ``Parameter``'s node in ``parameters_schema`` can state from the
# parameter's own fields, each with the fields that state it. Fixed per class,
# never per instance or per setting: a keyword is refused in ``json_schema_extra``
# whether or not this parameter, this policy or this setting makes the builder
# state it, so a declaration is valid or not once, where it is written, rather
# than on the day the cap comes on or a spec moves to ``REJECT``. ``maxItems``
# is stated from ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` when ``max_length`` is
# absent, and ``additionalProperties`` from the spec's unknown-arguments policy;
# both describe what those fields bound. ``const`` is the one keyword the
# builder never states: a single accepted value, which is the choices' to
# declare. test_the_keywords_refused_are_the_ones_the_builder_states holds the
# rest to what the builder states, both ways.
PARAMETER_SCHEMA_KEYWORDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "type": ("type", "nullable"),
        "items": ("items",),
        "minItems": ("min_length",),
        "maxItems": ("max_length",),
        "properties": ("fields",),
        "required": ("fields",),
        "additionalProperties": ("fields",),
        "format": ("format",),
        "minimum": ("minimum",),
        "maximum": ("maximum",),
        "enum": ("choices", "choice_labels"),
        "anyOf": ("choices", "choice_labels"),
        "const": ("choices", "choice_labels"),
        "default": ("default",),
        "description": ("help",),
    }
)

# As above, for an ``OutputField``'s node in ``output_schema``. Its choices are
# ``oneOf`` where a parameter's are ``anyOf``, and its prose is a ``title`` from
# its ``label`` where a parameter's is a ``description`` from its ``help``.
OUTPUT_FIELD_SCHEMA_KEYWORDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "type": ("type", "nullable"),
        "items": ("items",),
        "properties": ("fields",),
        "required": ("fields",),
        "format": ("format",),
        "enum": ("choices",),
        "oneOf": ("choices",),
        "const": ("choices",),
        "title": ("label",),
    }
)
