from __future__ import annotations

from django_service_specs.types.unknown_arguments import UnknownArguments


def test_passthrough_is_a_member_so_a_comparison_against_it_evaluates() -> None:
    # A transport that tests ``policy is UnknownArguments.PASSTHROUGH`` reads
    # False for either policy, where a missing member would raise.
    assert UnknownArguments("passthrough") is UnknownArguments.PASSTHROUGH
    assert UnknownArguments.IGNORE is not UnknownArguments.PASSTHROUGH


def test_the_two_policies_are_unchanged() -> None:
    assert [member.value for member in UnknownArguments] == ["reject", "ignore", "passthrough"]
