from __future__ import annotations

import functools

from django.core.checks import Error
from django.core.checks.registry import CheckRegistry

from django_service_specs.links.check_links import check_links
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.types.spec_link import SpecLink
from tests.links.links import RENAME, Declarer, NoOutput, listing


def registry_of(**specs: object) -> SpecRegistry:
    registry = SpecRegistry()
    for name, spec in specs.items():
        registry.register(name, spec)  # ty: ignore[invalid-argument-type]
    return registry


def test_a_registry_whose_links_bind_passes() -> None:
    registry = registry_of(notes=listing({"rename": RENAME, "other": Declarer()}), rename=RENAME)
    assert check_links(registry) == []


def test_an_unregistered_target_is_no_error() -> None:
    assert check_links(registry_of(notes=listing({"rename": RENAME}))) == []


def test_a_link_that_cannot_bind_is_an_error_naming_the_entry() -> None:
    registry = registry_of(notes=listing({"rename": RENAME}, NoOutput()))
    (error,) = check_links(registry)
    assert error == Error(
        "SelectorSpec.affordances['rename'] leads to a spec requiring ['pk'], and the spec "
        "declares no output, so only SpecLink arguments bind. Bind them: "
        "SpecLink(spec, arguments={read: field}).",
        obj="notes",
        id="django_service_specs.E001",
    )


def test_a_target_under_two_names_is_an_error() -> None:
    registry = registry_of(
        notes=listing({"rename": SpecLink(RENAME)}), rename=RENAME, rename_note=RENAME
    )
    (error,) = check_links(registry)
    assert error.id == "django_service_specs.E002"
    assert error.obj == "notes"
    assert error.msg.startswith(
        "affordances['rename']: The spec is registered under ['rename', 'rename_note']"
    )


def test_it_registers_as_a_system_check_in_one_line() -> None:
    registry = registry_of(notes=listing({"rename": RENAME}, NoOutput()))
    check_registry = CheckRegistry()
    check_registry.register(functools.partial(check_links, registry))
    (error,) = check_registry.run_checks()
    assert error.id == "django_service_specs.E001"
