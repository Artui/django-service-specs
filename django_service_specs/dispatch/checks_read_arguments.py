"""``checks_read_arguments`` - whether a spec's permission checks need the call's arguments to answer."""

from __future__ import annotations

from django_service_specs.authorization.utils import CLASS_LEVEL, SCOPE_LEVEL, declared_keywords
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def checks_read_arguments(spec: ServiceSpec | SelectorSpec | SpecSource) -> bool:
    """Whether one of ``spec``'s permission checks declares ``arguments`` on a question asked before any row is resolved.

    A transport that lists the operations a principal may run has no
    arguments to hand a check, and one that declares ``arguments`` is written
    to be given them. This answers, without calling any check, whether one
    does, so the transport can decide first: list the operation, hide it, or
    leave it to the call. It answers what a check *declares*, not what it
    does with ``None``: a check declaring ``arguments=None`` reads ``True``
    though it answers when handed nothing
    (test_a_check_declaring_arguments_with_a_default_still_declares_them).

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
