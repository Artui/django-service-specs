"""``resolve_target``: the target dispatch would find, found the way dispatch finds it.

Each case is asked of both functions, so "as dispatch would" is measured
rather than restated: the same result, or the same error at the same step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import (
    OPEN,
    PK,
    TENANT_SEEDS,
    Record,
    Refuse,
    Scoped,
    Titled,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

REQUIRED = ["This field is required."]


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def bob() -> Any:
    return make_user("bob")


class _NoteForm(forms.Form):
    title = forms.CharField()


class _Counting:
    """A RETRIEVE target selector that counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, pk: int) -> Any:
        self.calls += 1
        return Note.objects.filter(pk=pk)


def _update(
    check: Any = None, *, allow_none: bool = False, selector: Callable[..., Any] = note_by_pk
) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=[check] if check is not None else OPEN,
        validator=FormValidator(_NoteForm),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=selector, reads=PK, allow_none=allow_none
        ),
    )


def _bulk(check: Any = None) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=[check] if check is not None else OPEN,
        collection_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
    )


def _create(check: Any = None) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=[check] if check is not None else OPEN,
        validator=FormValidator(_NoteForm),
    )


def _found(resolved: Any) -> tuple[Any, Grant]:
    assert isinstance(resolved, tuple), resolved
    return resolved


# --- the same answer as dispatch -------------------------------------------------------


def test_a_row_is_the_row_dispatch_acts_on(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    spec = _update()
    target, grant = _found(resolve_target(spec, principal=ada, arguments={"pk": note.pk}))
    assert target == note
    result = dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "T"})
    assert result.instance == target


class _ServerPk(TypedDict):
    pk: int


def test_a_read_the_lookup_s_kwargs_provider_fills_is_not_demanded_as_dispatch_does_not(
    ada: Any,
) -> None:
    note = Note.objects.create(owner=ada, title="mine")

    def server() -> _ServerPk:
        return {"pk": note.pk}

    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=FormValidator(_NoteForm),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, kwargs=server
        ),
    )
    target, _ = _found(resolve_target(spec, principal=ada, arguments={}))
    assert target == note
    assert dispatch(spec, principal=ada, arguments={"title": "T"}).instance == note


def test_a_missing_row_is_dispatch_s_not_found(ada: Any) -> None:
    spec = _update()
    resolved = resolve_target(spec, principal=ada, arguments={"pk": 404})
    assert resolved == DispatchResult(kind="not_found")
    assert dispatch(spec, principal=ada, arguments={"pk": 404, "title": "T"}) == resolved


def test_a_missing_row_allow_none_lets_through_is_none(ada: Any) -> None:
    spec = _update(allow_none=True)
    target, grant = _found(resolve_target(spec, principal=ada, arguments={"pk": 404}))
    assert target is None
    result = dispatch(spec, principal=ada, arguments={"pk": 404, "title": "T"})
    assert (result.kind, result.instance) == ("instance", None)


def test_an_object_check_refuses_with_its_own_message_as_dispatch_does(ada: Any, bob: Any) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    spec = _update(Scoped())
    with pytest.raises(NotPermitted) as resolving:
        resolve_target(spec, principal=ada, arguments={"pk": theirs.pk})
    with pytest.raises(NotPermitted) as dispatching:
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk, "title": "T"})
    assert resolving.value.message == dispatching.value.message == "Not within your scope."


def test_an_empty_collection_is_returned_as_a_set(ada: Any) -> None:
    spec = _bulk()
    target, grant = _found(resolve_target(spec, principal=ada, arguments={}))
    assert list(target) == []
    assert target.model is Note
    assert list(dispatch(spec, principal=ada, arguments={}).instance) == []


def test_a_create_resolves_nothing(ada: Any) -> None:
    spec = _create()
    target, grant = _found(resolve_target(spec, principal=ada, arguments={}))
    assert target is None
    assert dispatch(spec, principal=ada, arguments={"title": "T"}).instance is None


def test_a_target_read_left_out_is_refused_as_dispatch_refuses_it(ada: Any) -> None:
    spec = _update()
    with pytest.raises(InvalidArguments) as resolving:
        resolve_target(spec, principal=ada, arguments={})
    with pytest.raises(InvalidArguments) as dispatching:
        dispatch(spec, principal=ada, arguments={"title": "T"})
    assert resolving.value.detail == dispatching.value.detail == {"pk": REQUIRED}


def test_arguments_that_are_no_mapping_are_refused_by_the_shape_check(ada: Any) -> None:
    arguments: Any = [1]
    with pytest.raises(InvalidArguments) as caught:
        resolve_target(_update(), principal=ada, arguments=arguments)
    assert caught.value.detail == {"non_field_errors": ["Expected an object."]}


# --- the scope check -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "arguments", "scope"),
    [
        (_bulk, {}, []),
        (_create, {}, None),
        (lambda check: _update(check, allow_none=True), {"pk": 404}, None),
    ],
    ids=["a-set", "a-create", "an-allow-none-miss"],
)
def test_the_scope_check_refuses_with_its_own_message(
    ada: Any, make: Callable[[Any], ServiceSpec], arguments: dict[str, Any], scope: Any
) -> None:
    check = Scoped(refuse_scope=True)
    with pytest.raises(NotPermitted) as caught:
        resolve_target(make(check), principal=ada, arguments=arguments)
    assert caught.value.message == "Not within your scope."
    assert check.scopes == [scope]


@pytest.mark.parametrize(
    ("make", "arguments", "scope"),
    [
        (_bulk, {}, []),
        (_create, {}, None),
        (lambda check: _update(check, allow_none=True), {"pk": 404}, None),
    ],
    ids=["a-set", "a-create", "an-allow-none-miss"],
)
def test_a_grant_that_checked_a_target_does_not_skip_the_checks_on_what_it_finds(
    ada: Any, make: Callable[[Any], ServiceSpec], arguments: dict[str, Any], scope: Any
) -> None:
    # resolve_target looks its target up itself, so a grant claiming the
    # checks ran says nothing about what this lookup finds: as dispatch with
    # no target=, it asks them.
    check = Scoped(refuse_scope=True)
    spec = make(check)
    grant = Grant(spec, ada, target_checked=True)
    with pytest.raises(NotPermitted):
        resolve_target(spec, principal=ada, arguments=arguments, grant=grant)
    assert check.scopes == [scope]


@pytest.mark.parametrize(
    ("make", "arguments", "target"),
    [
        (_bulk, {}, []),
        (_create, {"title": "T"}, None),
        (lambda check: _update(check, allow_none=True), {"pk": 404, "title": "T"}, None),
    ],
    ids=["a-set", "a-create", "an-allow-none-miss"],
)
def test_dispatch_handed_the_target_with_a_grant_that_checked_it_skips_the_scope_check(
    ada: Any, make: Callable[[Any], ServiceSpec], arguments: dict[str, Any], target: Any
) -> None:
    check = Scoped(refuse_scope=True)
    spec = make(check)
    grant = Grant(spec, ada, target_checked=True)
    dispatch(spec, principal=ada, arguments=arguments, grant=grant, target=target)
    assert check.scopes == []


class _ServerPk(TypedDict, total=False):
    pk: int


def test_a_filled_target_read_the_caller_sends_never_reaches_the_lookup(ada: Any, bob: Any) -> None:
    # The provider leaves the key out, as one that fills it for some users only
    # would: the caller's pk is dropped rather than looked up, as in dispatch.
    theirs = Note.objects.create(owner=bob, title="theirs")

    def scoped() -> _ServerPk:
        return {}

    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, kwargs=scoped
        ),
    )
    for call in (resolve_target, dispatch):
        with pytest.raises(InvalidArguments) as caught:
            call(spec, principal=ada, arguments={"pk": theirs.pk})
        assert caught.value.detail == {"pk": REQUIRED}


# --- dispatch's order, before any lookup -----------------------------------------------


def test_a_deactivated_principal_is_refused_before_any_query(
    ada: Any, django_assert_num_queries: Any
) -> None:
    ada.is_active = False
    with django_assert_num_queries(0), pytest.raises(PrincipalUnavailable):
        resolve_target(_update(), principal=ada, arguments={"pk": 1})


def test_a_class_level_refusal_is_raised_before_any_query(
    ada: Any, django_assert_num_queries: Any
) -> None:
    with django_assert_num_queries(0), pytest.raises(NotPermitted) as caught:
        resolve_target(_update(Refuse()), principal=ada, arguments={"pk": 1})
    assert caught.value.message == "Only editors may run this."


def test_a_grant_for_another_principal_is_refused(ada: Any, bob: Any) -> None:
    spec = _update()
    with pytest.raises(NotPermitted, match="The grant does not cover"):
        resolve_target(spec, principal=ada, arguments={"pk": 1}, grant=Grant(spec, bob))


def test_a_required_validator_field_left_out_is_not_refused(ada: Any) -> None:
    # The GET in front of a form carries the route's arguments alone; the POST
    # carries the form as well, and neither is refused for what the other has.
    note = Note.objects.create(owner=ada, title="mine")
    spec = _update()
    for arguments in ({"pk": note.pk}, {"pk": note.pk, "title": "T", "other": 1}):
        target, _ = _found(resolve_target(spec, principal=ada, arguments=arguments))
        assert target == note


def test_a_parameter_a_registered_seed_occupies_is_refused(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=note_by_pk,
            reads=Parameters.of(Parameter("tenant", "string")),
        ),
    )
    with pytest.raises(ImproperlyConfigured, match=r"\['tenant'\], which a registered pool seed"):
        resolve_target(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)


def test_a_validator_field_a_registered_seed_occupies_is_refused_as_dispatch_refuses_it(
    ada: Any,
) -> None:
    # The field is not among the target selector's parameters, which are all
    # resolve_target checks; the declaration is still wrong for every caller.
    note = Note.objects.create(owner=ada, title="mine")
    seeds = DEFAULT_POOL_SEEDS.extend(title=lambda *, user: "seeded")
    spec = _update()
    for call, arguments in (
        (resolve_target, {"pk": note.pk}),
        (dispatch, {"pk": note.pk, "title": "T"}),
    ):
        with pytest.raises(
            ImproperlyConfigured, match=r"\['title'\], which a registered pool seed"
        ):
            call(spec, principal=ada, arguments=arguments, pool_seeds=seeds)


def test_a_spec_declaring_no_permissions_is_refused_as_dispatch_refuses_it(ada: Any) -> None:
    spec = ServiceSpec(service=Record())
    with pytest.raises(ImproperlyConfigured, match="declares no permissions"):
        resolve_target(spec, principal=ada, arguments={})


def test_a_selector_spec_is_refused(ada: Any) -> None:
    spec: Any = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN)
    with pytest.raises(TypeError, match="resolve_target\\(\\) takes a ServiceSpec"):
        resolve_target(spec, principal=ada, arguments={})


def test_a_many_spec_is_refused_before_anything_runs(
    ada: Any, django_assert_num_queries: Any
) -> None:
    # Before the class-level check, which would refuse this principal: the
    # spec is the wrong kind for the question, whoever asks it.
    spec = ServiceSpec(service=Record(), permissions=[Refuse()], many=True, validator=Titled())
    with django_assert_num_queries(0), pytest.raises(ImproperlyConfigured) as refused:
        resolve_target(spec, principal=ada, arguments={"items": []})
    assert str(refused.value).startswith(
        "resolve_target() was handed a many spec, which declares no target selector"
    )


# --- handed on to dispatch --------------------------------------------------------------


def test_its_grant_covers_the_spec_and_principal_and_says_the_target_was_checked(
    ada: Any,
) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    spec = _update()
    _, grant = _found(resolve_target(spec, principal=ada, arguments={"pk": note.pk}))
    assert grant == Grant(spec, ada, target_checked=True)


def test_dispatch_handed_its_result_looks_up_nothing_and_checks_the_row_once(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    selector = _Counting()
    check = Scoped()
    spec = _update(check, selector=selector)
    target, grant = _found(resolve_target(spec, principal=ada, arguments={"pk": note.pk}))
    result = dispatch(
        spec, principal=ada, arguments={"pk": note.pk, "title": "T"}, target=target, grant=grant
    )
    assert selector.calls == 1
    assert check.rows == [note]
    assert result.instance == note


def test_its_grant_handed_on_without_the_target_covers_no_other_row(ada: Any, bob: Any) -> None:
    # The grant says the checks ran on the row resolve_target found; dispatch
    # finding a different row itself, from the arguments, asks them again.
    mine = Note.objects.create(owner=ada, title="mine")
    theirs = Note.objects.create(owner=bob, title="theirs")
    check = Scoped()
    spec = _update(check)
    target, grant = _found(resolve_target(spec, principal=ada, arguments={"pk": mine.pk}))
    assert target == mine
    with pytest.raises(NotPermitted):
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk, "title": "T"}, grant=grant)
    assert check.rows == [mine, theirs]
    assert spec.service.calls == []
