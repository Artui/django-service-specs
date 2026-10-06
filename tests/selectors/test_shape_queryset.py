"""Tests for ``shape_queryset`` — the five... now four shaping fields, minus filter_set."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Count, QuerySet

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note


def _bare_selector() -> Any:
    """A placeholder ``selector`` — shape_queryset never calls it."""
    return None


class TestNoShapingDeclared:
    def test_returns_the_queryset_unchanged(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector)
        qs = Permission.objects.all()
        assert shape_queryset(qs, spec, {}, source_label="x") is qs


@pytest.mark.django_db
class TestSelectRelated:
    def test_applied_to_the_queryset(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        result = shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert result.query.select_related == {"content_type": {}}

    def test_composes_with_a_real_fetch(self) -> None:
        """Not just a flag on the query — it actually joins and resolves."""
        permission = Permission.objects.first()
        assert permission is not None
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        result = shape_queryset(
            Permission.objects.filter(pk=permission.pk), spec, {}, source_label="x"
        )
        fetched = result.first()
        assert fetched is not None
        assert fetched.content_type == permission.content_type


@pytest.mark.django_db
class TestPrefetchRelated:
    def test_applied_to_the_queryset(self) -> None:
        group = Group.objects.create(name="editors")
        user = User.objects.create(username="ada")
        user.groups.add(group)

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            prefetch_related=["groups"],
        )
        result = shape_queryset(User.objects.all(), spec, {}, source_label="x")
        assert "groups" in result._prefetch_related_lookups
        assert list(result.get(pk=user.pk).groups.all()) == [group]


@pytest.mark.django_db
class TestAnnotations:
    def test_applied_to_the_queryset(self) -> None:
        content_type = ContentType.objects.first()
        assert content_type is not None
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            annotations={"perm_count": Count("permission")},
        )
        result = shape_queryset(ContentType.objects.all(), spec, {}, source_label="x")
        assert "perm_count" in result.query.annotation_select
        fetched = result.get(pk=content_type.pk)
        assert fetched.perm_count == Permission.objects.filter(content_type=content_type).count()


@pytest.mark.django_db
class TestExtendQueryset:
    def test_called_with_the_pool_and_the_queryset_so_far(self) -> None:
        captured: dict[str, Any] = {}

        def extend(*, queryset: QuerySet[Any], tenant: str) -> QuerySet[Any]:
            captured["queryset_type"] = type(queryset).__name__
            captured["tenant"] = tenant
            return queryset

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        shape_queryset(Permission.objects.all(), spec, {"tenant": "acme"}, source_label="x")
        assert captured == {"queryset_type": "QuerySet", "tenant": "acme"}

    def test_resolved_by_declare_to_receive(self) -> None:
        """A pool entry the callable did not declare is not forwarded."""

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset.none()

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        result = shape_queryset(
            Permission.objects.all(), spec, {"unused": "ignored"}, source_label="x"
        )
        assert result.count() == 0

    def test_a_read_the_pool_lacks_is_the_callable_s_own_error(self) -> None:
        """A transport shaping rows itself bound no arguments, so no caller
        could have sent ``title``, read or not: asking for it as a missing
        argument would ask for a value nobody can send."""
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            extend_queryset=lambda *, queryset, title: queryset.filter(title=title),
            reads=Parameters.of(Parameter("title", "string")),
        )
        ada = make_user("ada")

        with pytest.raises(TypeError, match="title"):
            shape_queryset(Note.objects.all(), spec, base_pool(user=ada), source_label="x")

    def test_runs_after_declarative_shaping(self) -> None:
        """``extend_queryset`` sees the already select_related-shaped queryset."""
        observed: dict[str, Any] = {}

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            observed["select_related"] = dict(queryset.query.select_related)
            return queryset

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
            extend_queryset=extend,
        )
        shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert observed["select_related"] == {"content_type": {}}

    def test_its_return_is_the_shaped_queryset(self) -> None:
        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset.none()

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        result = shape_queryset(Permission.objects.all(), spec, {}, source_label="x")
        assert list(result) == []


@pytest.mark.django_db
class TestNonQuerysetReturn:
    def test_raises_when_declarative_shaping_is_configured(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            select_related=["content_type"],
        )
        with pytest.raises(ImproperlyConfigured, match="not a Django QuerySet"):
            shape_queryset([{"id": 1}], spec, {}, source_label="ServiceSpec.output_selector_spec")

    def test_raises_when_extend_queryset_is_the_only_shaping_declared(self) -> None:
        """Covers the branch where extend_queryset alone triggers the guard."""

        def extend(*, queryset: QuerySet[Any]) -> QuerySet[Any]:
            return queryset

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_bare_selector, extend_queryset=extend)
        with pytest.raises(ImproperlyConfigured, match="not a Django QuerySet"):
            shape_queryset("not-a-queryset", spec, {}, source_label="SelectorSpec.selector")

    def test_error_names_the_source_label(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_bare_selector,
            annotations={"n": Count("id")},
        )
        with pytest.raises(ImproperlyConfigured, match="SelectorSpec.selector"):
            shape_queryset(object(), spec, {}, source_label="SelectorSpec.selector")
