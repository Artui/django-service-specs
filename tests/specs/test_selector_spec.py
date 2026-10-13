from __future__ import annotations

import dataclasses

import django_filters
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.filters.utils import NoteFilters, TitleFilter, UserFilters
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
        ({"kwargs": {"tenant": 1}}, "SelectorSpec.kwargs must be callable; got dict"),
        ({"progress_reporter": 3}, "SelectorSpec.progress_reporter must be callable; got int"),
        (
            {"preconditions": print},
            r"SelectorSpec.preconditions takes a sequence of callables; got "
            r"builtin_function_or_method\. Wrap a single one in a list: preconditions=\[\.\.\.\]\.",
        ),
        ({"preconditions": {print}}, "SelectorSpec.preconditions takes a sequence"),
        ({"preconditions": "print"}, "SelectorSpec.preconditions takes a sequence"),
        (
            {"preconditions": [print, 3]},
            r"SelectorSpec.preconditions\[1\] must be callable; got int\.",
        ),
    ],
)
def test_refuses_at_construction(kwargs: dict, message: str) -> None:
    base = {"kind": SelectorKind.LIST, "selector": list}
    with pytest.raises(ImproperlyConfigured, match=message):
        SelectorSpec(**{**base, **kwargs})


def test_the_providers_and_preconditions_are_kept_in_declaration_order() -> None:
    def scope() -> dict:
        return {}

    def sink() -> None:
        return None

    spec = listing(kwargs=scope, progress_reporter=sink, preconditions=[print, len])
    assert spec.kwargs is scope
    assert spec.progress_reporter is sink
    assert spec.preconditions == (print, len)
    bare = listing()
    assert (bare.kwargs, bare.progress_reporter, bare.preconditions) == (None, None, None)


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


class TestFilterSet:
    """A FilterSet's filters are reads: declared, described and checked as any other."""

    def test_its_filters_join_the_reads_after_the_author_s_own(self) -> None:
        own = Parameter("limit", "integer")
        spec = listing(reads=Parameters.of(own), filter_set=TitleFilter)
        assert spec.reads == Parameters.of(own, Parameter("title", "string"))
        assert spec.parameters() is spec.reads
        assert spec.filter_set is TitleFilter

    def test_a_copy_reads_the_filters_once(self) -> None:
        # ``replace`` hands the merged reads back to the constructor, where the
        # same filters arrive again: they are already there, not a second
        # declaration of the same name.
        spec = listing(filter_set=TitleFilter)
        copy = dataclasses.replace(spec, allow_none=False)
        assert copy == spec
        assert copy.reads == Parameters.of(Parameter("title", "string"))

    def test_a_copy_with_another_filter_set_reads_only_its_filters(self) -> None:
        # ``replace`` hands the merged reads back with the new filter set, so
        # the old one's filters would otherwise survive as if the author had
        # declared them.
        own = Parameter("limit", "integer")
        spec = listing(reads=Parameters.of(own), filter_set=TitleFilter)
        copy = dataclasses.replace(spec, filter_set=UserFilters)
        assert copy.reads == listing(reads=Parameters.of(own), filter_set=UserFilters).reads
        assert copy == listing(reads=Parameters.of(own), filter_set=UserFilters)

    def test_a_copy_without_a_filter_set_reads_the_author_s_own_alone(self) -> None:
        own = Parameter("limit", "integer")
        spec = listing(reads=Parameters.of(own), filter_set=TitleFilter)
        assert dataclasses.replace(spec, filter_set=None).reads == Parameters.of(own)

    def test_a_read_the_author_declared_as_the_filter_does_survives_a_copy(self) -> None:
        # Declared by the author and equal to the filter's, so never added as
        # the filter's: dropping the filter set leaves it declared.
        title = Parameter("title", "string")
        spec = listing(reads=Parameters.of(title), filter_set=TitleFilter)
        assert dataclasses.replace(spec, filter_set=None).reads == Parameters.of(title)

    def test_a_read_the_filter_declares_differently_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"\['title'\] are declared by two sources"):
            listing(reads=Parameters.of(Parameter("title", "integer")), filter_set=TitleFilter)

    def test_a_filter_named_after_a_reserved_seed_is_refused(self) -> None:
        class ByUser(django_filters.FilterSet):
            user = django_filters.CharFilter(field_name="owner__username")

        with pytest.raises(ImproperlyConfigured, match="SelectorSpec.reads"):
            listing(filter_set=ByUser)

    def test_the_input_schema_describes_each_filter(self) -> None:
        properties = spec_input_schema(listing(filter_set=NoteFilters))["properties"]
        assert properties["pk_range_min"] == {
            "type": "string",
            "format": "decimal",
            "description": "The `min` bound of `pk`.",
        }
        assert properties["kinds"]["type"] == "array"
        assert properties["kinds"]["items"]["enum"] == ["draft", "final"]

    def test_it_must_be_callable(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="SelectorSpec.filter_set must be callable"):
            listing(filter_set=3)

    def test_one_with_no_base_filters_is_refused_naming_it(self) -> None:
        # A duck-typed object takes ``(data, queryset)`` and declares no
        # filters, so it would be handed no data and never filter: the
        # caller's argument was dropped under IGNORE and refused as unknown
        # under REJECT. Refused where it is declared instead.
        class Duck:
            def __init__(self, data: object = None, queryset: object = None) -> None:
                self.qs = queryset

        with pytest.raises(ImproperlyConfigured) as refused:
            listing(filter_set=Duck)
        message = str(refused.value)
        assert "SelectorSpec.filter_set is Duck" in message
        assert "must be a django-filter FilterSet" in message
        assert "base_filters" in message
        # Not the callable check's wording: this one is callable.
        assert "must be callable" not in message

    def test_a_filterset_declaring_no_filters_is_accepted(self) -> None:
        # Holds the guard to the attribute's absence rather than its
        # emptiness: a real FilterSet with no filters narrows nothing and
        # declares nothing, which is a spec worth nothing but not a broken
        # one. A guard reading ``getattr(..., "base_filters", None) or ...``
        # refuses this.
        class Empty(django_filters.FilterSet):
            pass

        spec = listing(filter_set=Empty)
        assert spec.filter_set is Empty
        assert spec.reads == Parameters()


async def _extend(queryset: object) -> object:
    return queryset


class _AsyncFilterSet:
    """Called as ``filter_set(data=..., queryset=...)`` like a FilterSet, but ``async def``."""

    async def __call__(self, data: object, queryset: object) -> object:
        return queryset


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("extend_queryset", _extend, "SelectorSpec.extend_queryset is _extend"),
        ("filter_set", _AsyncFilterSet(), "SelectorSpec.filter_set is _AsyncFilterSet"),
    ],
)
def test_an_async_shaping_callable_is_refused(field: str, value: object, named: str) -> None:
    # Called from sync code while the rows are shaped, never awaited: the
    # coroutine would stand where the queryset should.
    with pytest.raises(ImproperlyConfigured, match=named + ", an async callable"):
        listing(**{field: value})


def test_a_filterset_class_is_not_mistaken_for_an_async_callable() -> None:
    # A class's ``__call__`` is its metaclass's, which is sync.
    assert listing(filter_set=TitleFilter).filter_set is TitleFilter
