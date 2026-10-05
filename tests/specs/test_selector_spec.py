from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
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
    assert SelectorSpec(kind=SelectorKind.LIST, selector=list).affordances is None


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


ARCHIVED = Affordance(code="archived", reason="Archived.", when=Q(archived=False))
RENAME = ServiceSpec(service=print, affordances=[ARCHIVED])


def listing(**kwargs: object) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, **kwargs)  # type: ignore[arg-type]


class TestAffordances:
    def test_a_mapping_of_names_to_service_specs_is_kept_as_given(self) -> None:
        mapping = {"rename": RENAME, "share": ServiceSpec(service=print)}
        assert listing(affordances=mapping).affordances is mapping

    def test_anything_but_a_mapping_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            listing(affordances=[RENAME])
        assert str(refused.value) == (
            "SelectorSpec.affordances must be a mapping of name -> ServiceSpec; got list."
        )

    # The guard is ``not isinstance(name, str) or not name``: one case per half.
    @pytest.mark.parametrize("name", [1, ""], ids=["not-a-string", "empty"])
    def test_a_key_must_be_a_non_empty_string(self, name: object) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            listing(affordances={name: RENAME})
        assert str(refused.value) == (
            f"SelectorSpec.affordances keys must be non-empty strings; got {name!r}."
        )

    @pytest.mark.parametrize(
        "value",
        ["rename_note", SelectorSpec(kind=SelectorKind.LIST, selector=list)],
        ids=["registry-name", "selector-spec"],
    )
    def test_a_value_must_be_a_service_spec(self, value: object) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            listing(affordances={"rename": value})
        assert str(refused.value).startswith(
            f"SelectorSpec.affordances['rename'] must be a ServiceSpec; got {type(value).__name__}."
        )

    def test_an_answer_named_like_a_declared_annotation_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            listing(affordances={"rename": RENAME}, annotations={"affordance__rename__archived": 1})
        assert str(refused.value).startswith(
            "SelectorSpec.affordances['rename'] generates the annotation "
            "'affordance__rename__archived', which `annotations` already declares."
        )

    def test_two_entries_generating_one_answer_name_are_refused(self) -> None:
        # ``a__b`` + ``c`` and ``a`` + ``b__c`` both name ``affordance__a__b__c``.
        first = ServiceSpec(
            service=print, affordances=[Affordance(code="c", reason="r", when=ARCHIVED.when)]
        )
        second = ServiceSpec(
            service=print, affordances=[Affordance(code="b__c", reason="r", when=ARCHIVED.when)]
        )
        with pytest.raises(ImproperlyConfigured) as refused:
            listing(affordances={"a__b": first, "a": second})
        assert str(refused.value).startswith(
            "SelectorSpec.affordances['a'] and ['a__b'] both generate the annotation "
            "'affordance__a__b__c'."
        )
