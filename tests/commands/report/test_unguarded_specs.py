from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.commands.report.unguarded_spec import UnguardedSpec
from django_service_specs.commands.report.unguarded_specs import unguarded_specs
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.types.unguarded_reason import UnguardedReason
from tests.commands_app.unguarded_registries import (
    OpenToAll,
    StaffOnly,
    mixed_registry,
    selector,
    service,
)
from tests.specs.utils import Foreign

OPEN = UnguardedReason.UNRESTRICTED


def _one(name: str, spec: Any) -> SpecRegistry:
    registry = SpecRegistry()
    registry.register(name, spec)
    return registry


class TestEachShape:
    """Every check in ``permissions`` must pass, so one real check guards the spec."""

    @pytest.mark.parametrize("make", [service, selector], ids=["service", "selector"])
    def test_one_unrestricted_is_reported(self, make: Any) -> None:
        assert unguarded_specs(_one("op", make(Unrestricted()))) == (UnguardedSpec("op", OPEN),)

    def test_two_unrestricted_are_reported_once(self) -> None:
        registry = _one("op", service(Unrestricted(), Unrestricted()))
        assert unguarded_specs(registry) == (UnguardedSpec("op", OPEN),)

    def test_a_subclass_of_unrestricted_is_still_unrestricted(self) -> None:
        # A project's own name for the allow is the same decision under another name.
        assert unguarded_specs(_one("op", service(OpenToAll()))) == (UnguardedSpec("op", OPEN),)

    def test_a_real_check_is_guarded(self) -> None:
        assert unguarded_specs(_one("op", service(StaffOnly()))) == ()

    @pytest.mark.parametrize(
        "checks",
        [(Unrestricted(), StaffOnly()), (StaffOnly(), Unrestricted())],
        ids=["real-check-last", "real-check-first"],
    )
    def test_a_real_check_beside_unrestricted_is_guarded(self, checks: Any) -> None:
        # Holds the "every" of the classification: an ``any`` would report both.
        assert unguarded_specs(_one("op", service(*checks))) == ()

    @pytest.mark.parametrize("empty", [[], ()], ids=["list", "tuple"])
    def test_empty_permissions_never_reach_a_registry(self, empty: Any) -> None:
        # The fourth shape has no member: the spec refuses it when it is built,
        # so no registry can hold it to be reported.
        with pytest.raises(ImproperlyConfigured, match=r"permissions is empty"):
            service(*empty)


class TestRegistries:
    def test_entries_come_back_in_registry_order(self) -> None:
        assert unguarded_specs(mixed_registry()) == (
            UnguardedSpec("open_service", OPEN),
            UnguardedSpec("open_twice", OPEN),
            UnguardedSpec("open_subclass", OPEN),
        )

    def test_an_empty_registry_reports_nothing(self) -> None:
        assert unguarded_specs(SpecRegistry()) == ()

    def test_a_subset_reports_in_its_own_order(self) -> None:
        registry = mixed_registry().subset("open_subclass", "guarded", "open_service")
        assert unguarded_specs(registry) == (
            UnguardedSpec("open_subclass", OPEN),
            UnguardedSpec("open_service", OPEN),
        )

    def test_a_merge_and_a_tag_view_are_read_like_any_registry(self) -> None:
        tagged = SpecRegistry()
        tagged.register("tagged_open", service(Unrestricted()), tags=("ops",))
        tagged.register("tagged_guarded", service(StaffOnly()), tags=("ops",))
        tagged.register("untagged_open", service(Unrestricted()))

        assert unguarded_specs(tagged.by_tag("ops")) == (UnguardedSpec("tagged_open", OPEN),)
        assert unguarded_specs(_one("first", service(Unrestricted())).merge(tagged)) == (
            UnguardedSpec("first", OPEN),
            UnguardedSpec("tagged_open", OPEN),
            UnguardedSpec("untagged_open", OPEN),
        )


class TestSourceObjects:
    """A declaration of another library's is judged by the spec it compiles to."""

    def test_a_source_compiling_to_an_open_spec_is_reported(self) -> None:
        assert unguarded_specs(_one("op", Foreign(compiled=service(Unrestricted())))) == (
            UnguardedSpec("op", OPEN),
        )

    def test_a_source_compiling_to_a_guarded_spec_is_not(self) -> None:
        assert unguarded_specs(_one("op", Foreign(compiled=service(StaffOnly())))) == ()

    def test_the_source_s_own_permissions_are_not_what_is_read(self) -> None:
        # A source answering ``permissions`` itself, as a drfs spec does with its
        # DRF permission classes, is not what dispatch runs; the compiled spec is.
        class Answering(Foreign):
            permissions = (Unrestricted(),)

        assert unguarded_specs(_one("op", Answering(compiled=service(StaffOnly())))) == ()
