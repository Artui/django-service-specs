from __future__ import annotations

import dataclasses

import pytest

from django_service_specs.commands.report.unguarded_spec import UnguardedSpec
from django_service_specs.types.unguarded_reason import UnguardedReason


def test_is_a_frozen_value() -> None:
    spec = UnguardedSpec("refund_order", UnguardedReason.UNRESTRICTED)
    assert spec == UnguardedSpec("refund_order", UnguardedReason.UNRESTRICTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "other"  # type: ignore[misc]
