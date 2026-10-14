"""The one reading of an unknown-arguments policy, shared by the shape check and its schema."""

from __future__ import annotations

from django_service_specs.types.unknown_arguments import UnknownArguments


def unknown_arguments_policy(value: UnknownArguments | str) -> UnknownArguments:
    """``value`` as a policy: a member, or its plain value, refusing what is not a policy.

    Normalized, so the policy's plain value works and a misspelt one raises
    ``ValueError`` rather than quietly falling through to one policy or the
    other. ``PASSTHROUGH`` is a valid member and not a policy, so it is
    refused here too: both readers test only ``is REJECT`` after this, and a
    member let through would run as ``IGNORE`` with nothing failing.
    """
    policy = UnknownArguments(value)
    if policy is UnknownArguments.PASSTHROUGH:
        raise ValueError(
            "UnknownArguments.PASSTHROUGH is refused: it is kept as a name and is not a "
            "policy, since an argument no parameter declares never reaches a callable. "
            "Pass REJECT, or IGNORE to drop the undeclared argument."
        )
    return policy
