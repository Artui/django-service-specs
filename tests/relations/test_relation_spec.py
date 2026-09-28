"""The shape every relation spec shares: required fields positional, options by keyword."""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any

import pytest

from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from tests.relations_app.models import Attachment, Author, Profile, Section, Tag

# Each concrete kind with the arguments its required fields take, in order.
_REQUIRED: tuple[tuple[type[RelationSpec], tuple[Any, ...]], ...] = (
    (ChildSpec, (Section, "catalog")),
    (ForwardRelationSpec, (Author,)),
    (ReverseOneToOneSpec, (Profile, "author")),
    (ManyToManySpec, (Tag,)),
    (GenericRelationSpec, (Attachment,)),
)


def test_every_kind_is_listed() -> None:
    # A kind added without a row here would escape every check below. Only the
    # package's own: the suite declares stand-in kinds of its own elsewhere.
    own = {
        kind
        for kind in RelationSpec.__subclasses__()
        if kind.__module__.startswith("django_service_specs.")
    }
    assert {kind for kind, _ in _REQUIRED} == own


@pytest.mark.parametrize(("kind", "required"), _REQUIRED)
class TestKeywordOnlyOptions:
    def test_the_required_fields_read_positionally(
        self, kind: type[RelationSpec], required: tuple[Any, ...]
    ) -> None:
        spec: Any = kind(*required)
        assert spec.model is required[0]

    def test_an_option_passed_positionally_is_refused(
        self, kind: type[RelationSpec], required: tuple[Any, ...]
    ) -> None:
        with pytest.raises(TypeError):
            kind(*required, "pk")

    def test_positional_is_exactly_the_required_fields(
        self, kind: type[RelationSpec], required: tuple[Any, ...]
    ) -> None:
        declared = fields(kind)
        positional = [f for f in declared if not f.kw_only]
        assert len(positional) == len(required)
        assert all(f.default is MISSING and f.default_factory is MISSING for f in positional)
        assert all(
            f.default is not MISSING or f.default_factory is not MISSING
            for f in declared
            if f.kw_only
        )
