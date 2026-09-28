from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.specs.utils import PK, Named, Nobody


def test_defaults_and_normalization() -> None:
    spec = SelectorSpec(
        kind="list",
        selector=list,
        permissions=[Unrestricted()],
        select_related=["author"],
        prefetch_related=["tags"],
    )
    assert spec.kind is SelectorKind.LIST
    assert isinstance(spec.permissions, tuple)
    assert spec.select_related == ("author",)
    assert spec.prefetch_related == ("tags",)
    assert spec.reads == Parameters()
    assert spec.parameters() is spec.reads
    assert spec.output() is None
    assert SelectorSpec(kind=SelectorKind.LIST, selector=list).permissions is None


def test_output_is_the_presenters() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, presenter=Named(), reads=PK)
    assert spec.output() == Named().output()
    assert spec.parameters() is PK


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "detail"}, "use SelectorKind.LIST or SelectorKind.RETRIEVE"),
        ({"selector": "books"}, "SelectorSpec.selector must be callable"),
        ({"permissions": Nobody()}, "must be a sequence of PermissionCheck"),
        ({"permissions": "staff"}, "must be a sequence of PermissionCheck"),
        ({"permissions": [Nobody]}, r"holds the class Nobody; pass an instance, Nobody\(\)"),
        ({"permissions": [object()]}, "holds object, which is not a PermissionCheck"),
        ({"reads": [Parameter("pk", "integer")]}, "reads must be Parameters"),
        (
            {"reads": Parameters.of(Parameter("user", "integer"))},
            r"\['user'\], which dispatch seeds",
        ),
        ({"presenter": Named}, "the class Named, which is not a Presenter"),
        ({"presenter": object()}, "is object, which is not a Presenter"),
        ({"allow_none": True}, "only a RETRIEVE has"),
        (
            {"select_related": "author"},
            r"select_related is a string; pass a sequence, \['author'\]",
        ),
        ({"prefetch_related": "tags"}, "prefetch_related is a string"),
        ({"extend_queryset": 3}, "extend_queryset must be callable"),
        ({"metadata": ["x"]}, "metadata must be a mapping; got list"),
    ],
)
def test_refuses_at_construction(kwargs: dict, message: str) -> None:
    base = {"kind": SelectorKind.LIST, "selector": list}
    with pytest.raises(ImproperlyConfigured, match=message):
        SelectorSpec(**{**base, **kwargs})


def test_extend_queryset_and_metadata_are_kept_as_given() -> None:
    meta = {"audit": "reads"}
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=list,
        extend_queryset=lambda queryset: queryset,
        metadata=meta,
    )
    assert spec.metadata is meta
