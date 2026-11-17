from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.utils import affordance_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.spec_link import SpecLink
from tests.dispatch.utils import Titled
from tests.links.links import (
    PK,
    RENAME,
    TENANT,
    TITLE,
    Declarer,
    listing,
    service,
    target,
    tenant_of,
    untyped,
)


class TestTheWrapper:
    def test_it_answers_the_linked_specs_conditions(self) -> None:
        link = SpecLink(RENAME)
        assert isinstance(link, AffordanceDeclarer)
        assert link.affordances == RENAME.affordances
        assert link.link_reads() == RENAME.link_reads()

    def test_a_bare_spec_and_its_link_give_the_same_annotations_and_schema(self) -> None:
        bare = listing({"rename": RENAME})
        linked = listing({"rename": SpecLink(RENAME, arguments={"pk": "id"})})
        assert affordance_schema(bare.affordances or {}) == affordance_schema(
            linked.affordances or {}
        )
        clash = {"affordance__rename__note_archived": True}
        for value in (RENAME, SpecLink(RENAME)):
            with pytest.raises(ImproperlyConfigured, match="already declares"):
                listing({"rename": value}, annotations=clash)

    def test_its_arguments_are_a_read_only_copy(self) -> None:
        given = {"pk": "id"}
        link = SpecLink(RENAME, arguments=given)
        given["title"] = "title"
        assert link.arguments == {"pk": "id"}
        assert isinstance(link.arguments, MappingProxyType)


class TestConstructionRefuses:
    @pytest.mark.parametrize(
        "value",
        ["rename", SelectorSpec(kind=SelectorKind.LIST, selector=list), SpecLink(RENAME)],
        ids=["name", "selector-spec", "link"],
    )
    def test_a_spec_that_is_not_a_service_spec(self, value: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match="SpecLink.spec must be a ServiceSpec"):
            SpecLink(value)

    def test_arguments_that_are_not_a_mapping(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="must be a mapping"):
            SpecLink(RENAME, arguments=[("pk", "id")])  # ty: ignore[invalid-argument-type]

    @pytest.mark.parametrize(
        "arguments",
        [{"": "id"}, {"pk": ""}, {1: "id"}, {"pk": 1}],
        ids=["empty-read", "empty-field", "read-not-str", "field-not-str"],
    )
    def test_arguments_that_are_not_names(self, arguments: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match="both non-empty strings"):
            SpecLink(RENAME, arguments=arguments)

    def test_a_read_the_target_does_not_take(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            SpecLink(RENAME, arguments={"slug": "title"})
        assert str(refused.value).startswith(
            "SpecLink.arguments binds ['slug'], which the linked spec does not read from a row: "
            "it reads ['pk', 'title']."
        )

    def test_a_read_the_targets_kwargs_fills(self) -> None:
        filled = service().derive(instance_selector_spec=target(PK, TENANT, kwargs=tenant_of))
        with pytest.raises(ImproperlyConfigured, match=r"binds \['tenant'\]"):
            SpecLink(filled, arguments={"tenant": "title"})

    def test_a_validator_field(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"binds \['title'\].*it reads \['pk'\]"):
            SpecLink(service(PK, validator=Titled()), arguments={"title": "title"})

    def test_a_declarer_with_no_reads_binds_nothing(self) -> None:
        assert Declarer().link_reads() == ()
        with pytest.raises(ImproperlyConfigured, match=r"binds \['pk'\]"):
            SpecLink(Declarer(), arguments={"pk": "id"})


class TestLinkReads:
    def test_the_targets_reads_then_the_specs_own(self) -> None:
        assert RENAME.link_reads() == ("pk", "title")
        assert service(PK, TITLE).link_reads() == ("pk", "title")

    def test_a_spec_with_no_target_binds_its_own_reads(self) -> None:
        assert service(own=(PK,)).link_reads() == ("pk",)

    def test_a_read_the_targets_kwargs_fills_is_left_out(self) -> None:
        spec = service().derive(instance_selector_spec=target(PK, TENANT, kwargs=tenant_of))
        assert spec.link_reads() == ("pk",)

    def test_an_untyped_provider_leaves_every_read(self) -> None:
        spec = service().derive(instance_selector_spec=target(PK, kwargs=untyped))
        assert spec.link_reads() == ("pk",)

    def test_a_read_the_specs_own_kwargs_fills_is_left_out(self) -> None:
        assert service(own=(TENANT, TITLE), kwargs=tenant_of).link_reads() == ("title",)
        assert service(own=(TITLE,), kwargs=untyped).link_reads() == ("title",)
