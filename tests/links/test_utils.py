from __future__ import annotations

from django_service_specs.links.utils import required_reads
from django_service_specs.types.spec_link import SpecLink
from tests.links.links import (
    PK,
    RENAME,
    TENANT,
    Declarer,
    declining,
    needs_pk,
    service,
    target,
    tenant_of,
    untyped,
)


def provided(kwargs: object) -> object:
    return service().derive(instance_selector_spec=target(PK, TENANT, kwargs=kwargs))


def test_the_targets_required_reads_are_required() -> None:
    assert required_reads(RENAME) == ("pk",)
    assert required_reads(SpecLink(RENAME)) == ("pk",)


def test_a_read_a_typed_provider_fills_or_may_decline_is_not() -> None:
    assert required_reads(provided(tenant_of)) == ("pk",)
    assert required_reads(provided(declining)) == ("pk",)


def test_an_untyped_provider_may_fill_any_read_less_one_it_requires() -> None:
    assert required_reads(provided(untyped)) == ()
    assert required_reads(provided(needs_pk)) == ("pk",)


def test_no_target_or_no_spec_requires_nothing() -> None:
    assert required_reads(service(own=(PK,))) == ()
    assert required_reads(Declarer()) == ()
