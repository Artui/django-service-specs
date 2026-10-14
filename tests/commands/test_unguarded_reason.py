from __future__ import annotations

import json

from django_service_specs.commands.unguarded_reason import UnguardedReason


def test_the_one_reason_a_registered_spec_can_be_open() -> None:
    # An empty ``permissions`` is refused when a spec is built and ``None`` when
    # it is registered, so neither has a member to be reported under.
    assert [reason.value for reason in UnguardedReason] == ["unrestricted"]


def test_a_reason_serializes_as_its_value() -> None:
    assert json.dumps(UnguardedReason.UNRESTRICTED) == '"unrestricted"'
