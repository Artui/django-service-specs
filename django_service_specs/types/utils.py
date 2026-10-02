"""Helpers shared across ``types/``, and with every reader of an affordance.

They live here rather than in ``affordances/`` for the reason ``types/`` exists.
``Affordance`` and ``ServiceSpec`` both need them at construction, and
``affordances/`` imports ``specs/``, so a home there would make the first spec
to load pull in the phase that imports it back, half-initialized. Nothing here
imports anything else in the package.
"""

from __future__ import annotations

from typing import Any, Final

# The pool names dispatch seeds per call rather than per process: the validated
# input (``data``), the resolved target (``instance``, ``collection``), and the
# values only a later step has - the service's return, as ``result`` in an output
# selector's pool, and the queryset being shaped, as ``queryset`` in
# ``extend_queryset``'s. An affordance condition reading one of them is a rule
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
