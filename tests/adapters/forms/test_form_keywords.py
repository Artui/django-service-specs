"""``form_keywords``: what a FormValidator's ``form_kwargs`` returns, for a page building the form.

Called through the package root rather than imported from its leaf, so each
test here fails on its own against a kernel without the function, rather than
the whole file failing to collect.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured

import django_service_specs
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, PK, make_user, notes_of
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db


def form_keywords(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
    return django_service_specs.form_keywords(*args, **kwargs)


class _Titled(forms.Form):
    """A form taking whatever ``form_kwargs`` returns, and keeping it."""

    title = forms.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.extra = {key: kwargs.pop(key) for key in list(kwargs) if key not in {"data", "files"}}
        super().__init__(*args, **kwargs)


class _Retitled(forms.ModelForm):
    """The ModelForm counterpart of ``_Titled``, for an update."""

    class Meta:
        model = Note
        fields = ["title"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        bound = {"data", "files", "instance"}
        self.extra = {key: kwargs.pop(key) for key in list(kwargs) if key not in bound}
        super().__init__(*args, **kwargs)


def _create(form_kwargs: Callable[..., Any] | None) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: data,
        permissions=OPEN,
        validator=FormValidator(_Titled, form_kwargs=form_kwargs),
    )


def _update(form_kwargs: Callable[..., Any]) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance, data: instance,
        permissions=OPEN,
        validator=FormValidator(_Retitled, form_kwargs=form_kwargs),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Note.objects.filter(pk=pk),
            reads=PK,
        ),
    )


def _collection(form_kwargs: Callable[..., Any]) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, collection, data: list(collection),
        permissions=OPEN,
        validator=FormValidator(_Titled, form_kwargs=form_kwargs),
        collection_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
    )


def _recorded() -> tuple[PoolSeeds, list[str]]:
    """Two seeds, ``club`` and ``locale``, each recording when it resolves."""
    resolved: list[str] = []

    def resolver(name: str) -> Any:
        def resolve(*, user: Any) -> str:
            resolved.append(name)
            return f"{name} of {user.username}"

        return resolve

    return DEFAULT_POOL_SEEDS.extend(club=resolver("club"), locale=resolver("locale")), resolved


class TestSeeds:
    def test_only_the_seed_form_kwargs_names_resolves(self) -> None:
        ada = make_user("ada")
        pool_seeds, resolved = _recorded()
        spec = _create(lambda *, club: {"club": club})
        assert form_keywords(spec, ada, pool_seeds=pool_seeds) == {"club": "club of ada"}
        assert resolved == ["club"]

    def test_a_catch_all_is_handed_every_seed_as_on_dispatch(self) -> None:
        ada = make_user("ada")
        pool_seeds, resolved = _recorded()
        spec = _create(lambda **kwargs: {"seen": sorted(kwargs)})
        # Never the call's context, which a catch-all receives only by naming it.
        assert form_keywords(spec, ada, pool_seeds=pool_seeds) == {
            "seen": ["club", "locale", "progress", "user"]
        }
        assert sorted(resolved) == ["club", "locale"]

    def test_with_no_pool_seeds_a_named_seed_is_not_handed(self) -> None:
        spec = _create(lambda *, club="none": {"club": club})
        assert form_keywords(spec, make_user("ada")) == {"club": "none"}

    def test_a_validator_with_no_form_kwargs_returns_nothing_and_resolves_no_seed(self) -> None:
        pool_seeds, resolved = _recorded()
        assert form_keywords(_create(None), make_user("ada"), pool_seeds=pool_seeds) == {}
        assert resolved == []


class TestThePool:
    def test_user_is_the_principal_and_progress_the_no_op_reporter(self) -> None:
        ada = make_user("ada")
        spec = _create(lambda *, user, progress: {"user": user, "progress": progress})
        keywords = form_keywords(spec, ada)
        assert keywords["user"] is ada
        assert keywords["progress"] is null_progress

    def test_form_kwargs_naming_the_call_context_is_handed_the_very_dict(self) -> None:
        # Empty, as a page's is when it builds the form: a mutant reading
        # ``call_context or {}`` would hand a fresh one in its place.
        context: dict[str, Any] = {}
        spec = _create(lambda *, call_context: {"context": call_context})
        assert form_keywords(spec, make_user("ada"), call_context=context)["context"] is context

    def test_with_no_call_context_each_call_is_handed_a_dict_of_its_own(self) -> None:
        spec = _create(lambda *, call_context: {"context": call_context})
        ada = make_user("ada")
        first, second = (form_keywords(spec, ada)["context"] for _ in range(2))
        assert first == second == {}
        assert first is not second

    def test_an_update_names_the_target_instance(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        spec = _update(lambda *, instance: {"row": instance})
        assert form_keywords(spec, ada, target=note)["row"] is note

    def test_a_collection_spec_names_the_target_collection(self) -> None:
        ada = make_user("ada")
        rows = notes_of(user=ada)
        spec = _collection(lambda *, collection: {"rows": collection})
        assert form_keywords(spec, ada, target=rows)["rows"] is rows

    def test_a_create_names_no_target(self) -> None:
        spec = _create(lambda **kwargs: {"seen": sorted(kwargs)})
        assert form_keywords(spec, make_user("ada"))["seen"] == ["progress", "user"]

    def test_a_spec_source_is_read_as_the_spec_it_compiles_to(self) -> None:
        spec = _create(lambda *, user: {"user": user})
        ada = make_user("ada")
        assert form_keywords(Foreign(compiled=spec), ada) == {"user": ada}


class TestRefusals:
    def test_a_key_the_bind_sets_itself_is_refused(self) -> None:
        spec = _create(lambda: {"instance": None})
        with pytest.raises(ImproperlyConfigured, match="form_kwargs returned 'instance', which"):
            form_keywords(spec, make_user("ada"))

    def test_an_answer_that_is_not_a_mapping_is_refused(self) -> None:
        spec = _create(lambda: [("title", "x")])
        with pytest.raises(ImproperlyConfigured, match="it returns a mapping of constructor"):
            form_keywords(spec, make_user("ada"))

    def test_a_selector_spec_is_refused(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN)
        with pytest.raises(TypeError) as refused:
            form_keywords(spec, make_user("ada"))
        assert str(refused.value) == (
            "form_keywords() reads a ServiceSpec validated by a FormValidator; "
            "this SelectorSpec has no Validator."
        )

    @pytest.mark.parametrize(
        ("validator", "named"),
        [(None, "no Validator"), (DataclassValidator, "a DataclassValidator")],
    )
    def test_a_service_spec_validated_by_no_form_is_refused(
        self, validator: Any, named: str
    ) -> None:
        @dataclass
        class Titled:
            title: str

        spec = ServiceSpec(
            service=lambda *, data: data,
            permissions=OPEN,
            validator=None if validator is None else validator(Titled),
        )
        with pytest.raises(TypeError) as refused:
            form_keywords(spec, make_user("ada"))
        assert str(refused.value) == (
            "form_keywords() reads a ServiceSpec validated by a FormValidator; "
            f"this ServiceSpec has {named}."
        )


class TestTheDispatchRoute:
    """The page's call and dispatch's hand one ``form_kwargs`` the same names."""

    @pytest.mark.parametrize("catch_all", [False, True])
    def test_both_routes_hand_form_kwargs_the_same_pool(self, catch_all: bool) -> None:
        seen: list[dict[str, Any]] = []

        def named(*, user: Any, club: Any, instance: Any, call_context: Any) -> dict[str, Any]:
            seen.append({"user": user, "club": club, "instance": instance, "ctx": call_context})
            return {}

        def every(**kwargs: Any) -> dict[str, Any]:
            seen.append(kwargs)
            return {}

        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        spec = _update(every if catch_all else named)
        pool_seeds, _ = _recorded()
        page: dict[str, Any] = {}
        call: dict[str, Any] = {}
        form_keywords(spec, ada, pool_seeds=pool_seeds, target=note, call_context=page)
        dispatch(
            spec,
            principal=ada,
            arguments={"pk": note.pk, "title": "Final"},
            pool_seeds=pool_seeds,
            call_context=call,
        )
        on_the_page, on_dispatch = seen
        assert on_the_page.keys() == on_dispatch.keys()
        assert on_the_page["user"] is on_dispatch["user"] is ada
        assert on_the_page["club"] == on_dispatch["club"] == "club of ada"
        assert on_the_page["instance"] == on_dispatch["instance"] == note
        if not catch_all:
            assert on_the_page["ctx"] is page
            assert on_dispatch["ctx"] is call
