from __future__ import annotations

import pytest

from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.utils import unknown_arguments_policy


@pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])
def test_a_policy_is_read_as_its_member_from_the_member_or_its_value(
    policy: UnknownArguments,
) -> None:
    assert unknown_arguments_policy(policy) is policy
    assert unknown_arguments_policy(policy.value) is policy


def test_passthrough_is_refused_naming_the_two_policies() -> None:
    with pytest.raises(ValueError, match="Pass REJECT, or IGNORE"):
        unknown_arguments_policy(UnknownArguments.PASSTHROUGH)


def test_a_value_that_is_no_member_is_refused() -> None:
    with pytest.raises(ValueError, match="'drop' is not a valid UnknownArguments"):
        unknown_arguments_policy("drop")
