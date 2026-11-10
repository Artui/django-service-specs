from __future__ import annotations

from enum import Enum


class UnknownArguments(str, Enum):
    """The closed argument set's policy, applied at every level of nesting."""

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
