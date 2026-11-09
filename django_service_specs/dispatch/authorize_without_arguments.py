"""``authorize_without_arguments`` - the permission questions a call asks before its arguments name anything."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import asks_scope_of_nothing
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def authorize_without_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    *,
    grant: Grant | None = None,
    call_context: dict[str, Any] | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> Grant:
    """Ask ``spec``'s permission checks for ``principal`` as a call with no arguments would.

    For a transport that has to answer before it has a call's arguments, or
    without them: a listing filtered by permission, an OPTIONS answer, a
    completion, a call whose arguments failed their shape. Two questions, the
    two dispatch asks before the arguments name a row or a set:
    [`authorize`][django_service_specs.dispatch.authorize.authorize], the
    class-level one, and, for a ``ServiceSpec`` with no target selector (a
    create),
    [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope]
    of ``None``. Any other spec's scope question is of a row or a set only the
    arguments name, and stays unasked. The rule is the one
    [`checks_read_arguments`][django_service_specs.dispatch.checks_read_arguments.checks_read_arguments]
    reads a spec's declarations by, so a check it says declares ``arguments``
    is a check this asks. Each question is handed ``arguments=None``, the
    kernel's word for a call with none to hand.

    **Nothing is caught.** What either question raises reaches the caller as
    it was raised: a refusal (``NotPermitted``, a check's own exception), a
    configuration error (``ImproperlyConfigured``: a spec declaring no
    permissions and no ``grant``, a check left awaiting its answer), and a
    check that cannot answer without the arguments it reads
    (``arguments["owner"]`` on ``None`` raises ``TypeError``). Which of those
    is a refusal, which hides an operation and which waits for the call is the
    transport's policy, so the transport wraps this in its own ``try``.

    ``grant``, ``call_context`` and ``pool_seeds`` are handed to both questions
    as ``authorize`` takes them: a covering grant answers the class-level
    question and a grant for another spec or principal is refused; both
    questions are handed the one ``call_context`` dict, a fresh one where none
    is handed, so what a check writes to it the next question reads; and each
    question resolves from ``pool_seeds`` the seeds its own checks name. A deactivated
    principal handed with ``pool_seeds`` raises ``PrincipalUnavailable`` before
    any check is asked, as dispatch refuses one; without ``pool_seeds`` it is
    asked exactly as ``authorize`` asks it. A grant's ``target_checked`` does
    not answer the scope question here: it covers a target handed to dispatch
    as ``target=``, and a call with no arguments hands none, so dispatch would
    ask it.

    ``spec`` may be a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource], asked as
    the spec it compiles to.

    Returns:
        The grant ``authorize`` returned: the covering ``grant`` handed in,
        unchanged, or a fresh one for the spec and ``principal``, which claims
        no target, so a ``dispatch`` handed it still asks the scope question.
    """
    # Compiled first, since the predicate reads the spec's class and a source
    # is neither (test_a_source_compiling_to_a_create_is_asked_the_scope_of_nothing).
    spec = kernel_spec(spec)
    # Here rather than left to each question, which would make a dict of its own
    # (test_handed_no_call_context_both_questions_share_one). Never ``or``: an
    # empty dict the caller handed is the one it reads afterwards
    # (test_both_questions_are_handed_the_one_call_context).
    call_context = {} if call_context is None else call_context
    granted = authorize(
        spec,
        principal,
        grant=grant,
        arguments=None,
        call_context=call_context,
        pool_seeds=pool_seeds,
    )
    if asks_scope_of_nothing(spec):
        # With the target flag cleared, as dispatch clears it where no target
        # is handed in (test_a_grant_that_checked_the_target_still_asks_the_scope_of_nothing).
        authorize_scope(
            spec,
            principal,
            None,
            grant=replace(granted, target_checked=False),
            arguments=None,
            call_context=call_context,
            pool_seeds=pool_seeds,
        )
    return granted
