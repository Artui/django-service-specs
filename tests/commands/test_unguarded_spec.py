from __future__ import annotations

import dataclasses

import pytest

from django_service_specs.commands.unguarded_reason import UnguardedReason
from django_service_specs.commands.unguarded_spec import UnguardedSpec


def test_is_a_frozen_value() -> None:
    spec = UnguardedSpec("refund_order", UnguardedReason.UNRESTRICTED)
    assert spec == UnguardedSpec("refund_order", UnguardedReason.UNRESTRICTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "other"  # type: ignore[misc]
