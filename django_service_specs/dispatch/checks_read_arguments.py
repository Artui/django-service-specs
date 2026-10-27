"""``checks_read_arguments`` - whether a spec's permission checks need the call's arguments to answer."""

from __future__ import annotations

from django_service_specs.authorization.utils import CLASS_LEVEL, SCOPE_LEVEL, declared_keywords
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def checks_read_arguments(spec: ServiceSpec | SelectorSpec | SpecSource) -> bool:
    """Whether one of ``spec``'s permission checks declares ``arguments`` on a question asked before any row is resolved.

    A transport that lists the operations a principal may run asks the checks
    with no arguments, because a listing has none, and a check that reads them
    cannot answer there: it raises on their absence, and the listing has
    hidden the operation by calling the check and catching the raise. This
    answers without the call, so the transport can decide first (list it,
    hide it, or ask with the arguments it does have).

    The questions are the two
    [`authorize`][django_service_specs.dispatch.authorize.authorize] and a
    create's
    [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope]
    of nothing ask before the call's arguments name anything: every check's
    ``has_permission``, and, for a ``ServiceSpec`` with no target selector,
    its ``has_scope_permission`` too. A service spec with a target selector
    asks the scope question of the row or set that selector resolves, and a
    check's ``has_object_permission`` is asked of a resolved row; neither
    exists without the arguments, so neither is read here. The declaration is
    read as ``authorize`` hands it: a check declares ``arguments`` by name,
    through the same reading (``declared_keywords``) that decides whether it
    is handed them, so the two cannot disagree.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to. A spec declaring no permissions has no checks and answers
    ``False``; dispatch refuses it at the call.

    Each part of the rule has a test that fails without it: the class-level
    question (test_a_check_declaring_arguments_on_the_class_question_reads_them),
    a create's scope question
    (test_a_check_declaring_arguments_only_on_the_scope_question_reads_them_in_a_create),
    and the scope question left out beside a target selector or on a selector
    spec, one arc to coverage with two conjuncts
    (test_the_scope_question_is_not_asked_where_a_target_or_a_selector_stands
    holds the target selector's; the selector spec's, which has no
    ``target_selector_spec``, is held by every ``_listing`` case).
    """
    spec = kernel_spec(spec)
    questions = [CLASS_LEVEL]
    if isinstance(spec, ServiceSpec) and spec.target_selector_spec() is None:
        questions.append(SCOPE_LEVEL)
    return any(
        "arguments" in declared_keywords(check, method, positional=positional)
        for check in spec.permissions or ()
        for method, positional in questions
    )
