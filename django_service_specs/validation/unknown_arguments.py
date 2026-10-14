"""``UnknownArguments`` - what happens to an argument no parameter declares."""

from __future__ import annotations

from enum import Enum


class UnknownArguments(str, Enum):
    """The closed argument set's policy, applied at every level of nesting.

    ``REJECT`` is the default everywhere. An untrusted caller's undeclared key
    is refused before it costs a query, and a trusted one's typo - a command's
    misspelt option, a task enqueued with last month's argument name - fails
    where the caller can see it rather than being dropped on the floor.

    There is no pass-through policy. An undeclared argument reaching a
    callable is exactly what the closed set exists to prevent: on a selector,
    with no Validator in front of it, it would let a caller supply a keyword
    the operation's author never offered. ``PASSTHROUGH`` is a member and not
    a policy, and every function taking one refuses it.
    """

    REJECT = "reject"
    """Refuse the undeclared key with ``InvalidArguments``, at the level it appeared."""

    IGNORE = "ignore"
    """Drop the undeclared key and carry on."""

    PASSTHROUGH = "passthrough"
    """Kept as a name, and refused as a policy.

    It is here for the current release of djangorestframework-services, whose
    published transports compare a policy against it by identity: with the
    member, that comparison is false for either policy, where its absence
    would raise ``AttributeError``. It is never run.
    [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
    and
    [`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema]
    raise ``ValueError`` for it where they read the policy, so ``dispatch``,
    ``adispatch``, ``check_call``, ``bind_arguments`` and ``spec_input_schema``
    refuse it too, rather than running it as ``IGNORE``.
    """
