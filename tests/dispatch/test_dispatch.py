from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import F, Q, Value
from django.db.models.functions import Concat

from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import (
    OPEN,
    PK,
    TENANT_SEEDS,
    OwnerOnly,
    Record,
    Refuse,
    Titled,
    make_user,
    note_by_pk,
    notes_of,
    shaping_refused,
)
from tests.dispatch_app.models import Note

LIST = SelectorKind.LIST
RETRIEVE = SelectorKind.RETRIEVE

pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def bob() -> Any:
    return make_user("bob")


def retrieve(**kwargs: Any) -> SelectorSpec:
    kwargs.setdefault("selector", note_by_pk)
    kwargs.setdefault("reads", PK)
    kwargs.setdefault("permissions", OPEN)
    return SelectorSpec(kind=RETRIEVE, **kwargs)


def nested(kind: SelectorKind, **kwargs: Any) -> SelectorSpec:
    # A nested selector's permissions are never read; it declares none.
    return SelectorSpec(kind=kind, **kwargs)


class Boom(Exception):
    """Raised by a service after it wrote, to see whether the write survives."""


# --- A selector spec -----------------------------------------------------------------


def test_a_list_returns_the_principals_rows_as_a_list(ada: Any, bob: Any) -> None:
    mine = Note.objects.create(owner=ada, title="mine")
    Note.objects.create(owner=bob, title="theirs")
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)

    result = dispatch(spec, principal=ada, arguments={})

    assert result.kind == "list"
    assert list(result.value) == [mine]


def test_a_retrieve_returns_its_row(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")

    result = dispatch(retrieve(), principal=ada, arguments={"pk": note.pk})

    assert result == DispatchResult(kind="instance", value=note)


def test_a_missing_row_is_not_found_and_returned_rather_than_raised(ada: Any) -> None:
    assert dispatch(retrieve(), principal=ada, arguments={"pk": 404}) == DispatchResult(
        kind="not_found"
    )


def test_a_retrieve_raising_does_not_exist_is_not_found(ada: Any) -> None:
    def by_get(*, pk: int) -> Note:
        return Note.objects.get(pk=pk)

    result = dispatch(retrieve(selector=by_get), principal=ada, arguments={"pk": 404})

    assert result == DispatchResult(kind="not_found")


def test_a_list_raising_does_not_exist_is_a_fault_and_passes_through(ada: Any) -> None:
    def broken(*, user: Any) -> Any:
        return Note.objects.get(pk=404)

    spec = SelectorSpec(kind=LIST, selector=broken, permissions=OPEN)

    with pytest.raises(Note.DoesNotExist):
        dispatch(spec, principal=ada, arguments={})


def test_allow_none_returns_none_and_never_object_checks_it(ada: Any) -> None:
    check = OwnerOnly()

    result = dispatch(
        retrieve(allow_none=True, permissions=[check]), principal=ada, arguments={"pk": 404}
    )

    assert result == DispatchResult(kind="instance", value=None)
    assert check.rows == []


def test_a_refused_principal_learns_nothing_about_which_rows_exist(ada: Any) -> None:
    selector = Record()
    spec = retrieve(selector=selector, permissions=[Refuse()])

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={"pk": 1})

    assert caught.value.message == "Only editors may run this."
    assert selector.calls == []


def test_arguments_are_checked_before_the_principal_is_authorized(ada: Any) -> None:
    # The principal is refused too, so the shape check answering proves it ran first.
    spec = retrieve(permissions=[Refuse()])

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"pk": ["This field is required."]}


def test_the_object_level_check_refuses_another_owners_row(ada: Any, bob: Any) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()

    with pytest.raises(NotPermitted) as caught:
        dispatch(retrieve(permissions=[check]), principal=ada, arguments={"pk": theirs.pk})

    assert caught.value.message == "Only the owner may touch this note."
    assert check.rows == [theirs]


def test_the_object_level_check_never_runs_on_a_list(ada: Any, bob: Any) -> None:
    Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()
    spec = SelectorSpec(kind=LIST, selector=lambda: Note.objects.all(), permissions=[check])

    result = dispatch(spec, principal=ada, arguments={})

    assert len(result.value) == 1
    assert check.rows == []


def test_a_covering_grant_stands_in_for_the_class_level_check(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    spec = retrieve(permissions=[Refuse()])

    result = dispatch(spec, principal=ada, arguments={"pk": note.pk}, grant=Grant(spec, ada))

    assert result.value == note


def test_a_grant_for_another_principal_is_refused(ada: Any, bob: Any) -> None:
    spec = retrieve()

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={"pk": 1}, grant=Grant(spec, bob))

    assert caught.value.message == "The grant does not cover this spec and principal."


def test_a_grant_that_checked_the_target_skips_the_object_level_check(ada: Any, bob: Any) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()
    spec = retrieve(permissions=[check])
    grant = Grant(spec, ada, target_checked=True)

    result = dispatch(spec, principal=ada, arguments={"pk": theirs.pk}, grant=grant)

    assert result.value == theirs
    assert check.rows == []


def test_a_selector_receives_the_pool_and_only_its_declared_reads(ada: Any) -> None:
    selector = Record(returns=[])
    reads = Parameters.of(Parameter("q", "string"), Parameter("limit", "integer"))
    spec = SelectorSpec(kind=LIST, selector=selector, reads=reads, permissions=OPEN)

    dispatch(spec, principal=ada, arguments={"q": "x"})

    assert selector.calls == [{"user": ada, "progress": null_progress, "q": "x"}]


def test_a_selector_spec_s_rows_are_shaped(ada: Any, bob: Any) -> None:
    Note.objects.create(owner=ada, title="mine")
    Note.objects.create(owner=bob, title="theirs")

    def mine_only(*, queryset: Any, user: Any) -> Any:
        return queryset.filter(owner=user)

    spec = SelectorSpec(
        kind=LIST,
        selector=lambda: Note.objects.all(),
        permissions=OPEN,
        select_related=["owner"],
        annotations={"label": Concat(F("title"), Value("!"))},
        extend_queryset=mine_only,
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert [note.label for note in result.value] == ["mine!"]


def test_an_async_selector_is_bridged_by_sync_dispatch(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")

    async def selector(*, pk: int) -> Any:
        return Note.objects.filter(pk=pk)

    result = dispatch(retrieve(selector=selector), principal=ada, arguments={"pk": note.pk})

    assert result.value == note


# --- Shaping names the selector that returned something else --------------------------


def _returns_a_list(**pool: Any) -> list[Any]:
    return []


def _returns_an_object(**pool: Any) -> object:
    return object()


@pytest.mark.parametrize(
    ("spec", "source", "returned"),
    [
        (
            SelectorSpec(
                kind=LIST, selector=_returns_a_list, permissions=OPEN, select_related=["owner"]
            ),
            "SelectorSpec.selector",
            "list",
        ),
        (
            ServiceSpec(
                service=Record(),
                permissions=OPEN,
                instance_selector_spec=nested(
                    RETRIEVE, selector=_returns_an_object, reads=PK, select_related=["owner"]
                ),
            ),
            "ServiceSpec.instance_selector_spec.selector",
            "object",
        ),
        (
            ServiceSpec(
                service=Record(),
                permissions=OPEN,
                collection_selector_spec=nested(
                    LIST, selector=_returns_a_list, select_related=["owner"]
                ),
            ),
            "ServiceSpec.collection_selector_spec.selector",
            "list",
        ),
        (
            ServiceSpec(
                service=Record(),
                permissions=OPEN,
                output_selector_spec=nested(
                    RETRIEVE, selector=_returns_an_object, select_related=["owner"]
                ),
            ),
            "ServiceSpec.output_selector_spec.selector",
            "object",
        ),
    ],
    ids=["selector", "instance", "collection", "output"],
)
def test_shaping_a_non_queryset_names_the_selector_that_returned_it(
    ada: Any, spec: Any, source: str, returned: str
) -> None:
    arguments = {"pk": 1} if source.startswith("ServiceSpec.instance") else {}

    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(spec, principal=ada, arguments=arguments)

    assert str(caught.value) == shaping_refused(source, returned)


# --- A service spec --------------------------------------------------------------------


def test_a_create_runs_with_the_validated_values_and_no_target(ada: Any) -> None:
    service = Record(returns="created")
    validator = Titled()
    spec = ServiceSpec(service=service, permissions=OPEN, validator=validator)

    result = dispatch(spec, principal=ada, arguments={"title": "  Hello "})

    assert service.calls == [
        {"user": ada, "progress": null_progress, "data": {"title": "Hello"}, "title": "Hello"}
    ]
    assert validator.calls[0][1].target is None
    assert result == DispatchResult(
        kind="instance",
        value="created",
        service_result="created",
        instance=None,
        data={"title": "Hello"},
    )


def test_an_update_resolves_the_row_before_validating_and_hands_it_to_both(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="old")
    service = Record(returns="updated")
    validator = Titled()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "new"})

    # The Validator sees only its own arguments, never the selector's ``pk``.
    assert validator.calls[0][0] == {"title": "new"}
    assert validator.calls[0][1].principal is ada
    assert validator.calls[0][1].target == note
    assert service.calls == [
        {
            "user": ada,
            "progress": null_progress,
            "data": {"title": "new"},
            "title": "new",
            "instance": note,
        }
    ]
    assert result.instance == note
    assert result.data == {"title": "new"}


def test_a_target_selector_receives_only_its_own_reads(ada: Any) -> None:
    selector = Record(returns=None)
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=Titled(),
        instance_selector_spec=nested(RETRIEVE, selector=selector, reads=PK, allow_none=True),
    )

    dispatch(spec, principal=ada, arguments={"pk": 7, "title": "t"})

    assert selector.calls == [{"user": ada, "progress": null_progress, "pk": 7}]


def test_an_update_of_a_missing_row_is_not_found_and_nothing_else_runs(ada: Any) -> None:
    service = Record()
    validator = Titled()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": 404, "title": "t"})

    assert result == DispatchResult(kind="not_found")
    assert validator.calls == []
    assert service.calls == []


def test_an_upsert_s_missing_row_reaches_the_service_as_none_unchecked(ada: Any) -> None:
    check = OwnerOnly()
    service = Record(returns="upserted")
    spec = ServiceSpec(
        service=service,
        permissions=[check],
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK, allow_none=True),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": 404})

    assert service.calls == [{"user": ada, "progress": null_progress, "data": {}, "instance": None}]
    assert check.rows == []
    assert result.value == "upserted"


def test_a_service_s_target_is_object_checked_before_validation(ada: Any, bob: Any) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=[OwnerOnly()],
        validator=validator,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
    )

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk, "title": "t"})

    assert caught.value.message == "Only the owner may touch this note."
    assert validator.calls == []


def test_a_refused_principal_never_reaches_the_target_selector(ada: Any) -> None:
    selector = Record()
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        instance_selector_spec=nested(RETRIEVE, selector=selector, reads=PK),
    )

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={"pk": 1})

    assert caught.value.message == "Only editors may run this."
    assert selector.calls == []


def test_a_collection_is_passed_as_collection_and_never_object_checked(ada: Any, bob: Any) -> None:
    Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()
    service = Record(returns=0)
    spec = ServiceSpec(
        service=service,
        permissions=[check],
        collection_selector_spec=nested(LIST, selector=lambda: Note.objects.all()),
    )

    result = dispatch(spec, principal=ada, arguments={})

    (pool,) = service.calls
    assert set(pool) == {"user", "progress", "data", "collection"}
    assert list(pool["collection"]) == list(Note.objects.all())
    assert result.instance is pool["collection"]
    assert result.kind == "instance"
    assert check.rows == []


def test_the_output_selector_re_reads_with_only_result_in_its_pool(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    reread = Record(returns=Note.objects.filter(pk=note.pk))
    spec = ServiceSpec(
        service=Record(returns=note),
        permissions=OPEN,
        validator=Titled(),
        output_selector_spec=nested(
            RETRIEVE,
            selector=reread,
            annotations={"label": Concat(F("title"), Value("!"))},
        ),
    )

    result = dispatch(spec, principal=ada, arguments={"title": "t"})

    assert reread.calls == [{"user": ada, "progress": null_progress, "result": note}]
    assert result.kind == "instance"
    assert result.value.label == "mine!"
    assert result.service_result is note


def test_a_list_output_selector_makes_the_result_a_list(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    spec = ServiceSpec(
        service=Record(returns=None),
        permissions=OPEN,
        output_selector_spec=nested(LIST, selector=notes_of),
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert result.kind == "list"
    assert list(result.value) == [note]


@pytest.mark.parametrize("how", ["returns nothing", "raises DoesNotExist"])
def test_an_output_selector_that_finds_nothing_is_none_not_not_found(ada: Any, how: str) -> None:
    def gone(*, result: Any) -> Any:
        if how == "raises DoesNotExist":
            return Note.objects.get(pk=404)
        return Note.objects.none()

    spec = ServiceSpec(
        service=Record(returns="done"),
        permissions=OPEN,
        output_selector_spec=nested(RETRIEVE, selector=gone),
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert result == DispatchResult(kind="instance", value=None, service_result="done", data={})


@pytest.mark.parametrize(("atomic", "survives"), [(True, False), (False, True)])
def test_the_service_runs_atomically_when_the_spec_says_so(
    ada: Any, atomic: bool, survives: bool
) -> None:
    def write_then_fail(*, user: Any) -> None:
        Note.objects.create(owner=user, title="half-done")
        raise Boom

    spec = ServiceSpec(service=write_then_fail, permissions=OPEN, atomic=atomic)

    with pytest.raises(Boom):
        dispatch(spec, principal=ada, arguments={})

    assert Note.objects.filter(title="half-done").exists() is survives


def test_an_async_service_is_awaited_by_sync_dispatch(ada: Any) -> None:
    async def service(*, title: str) -> str:
        return f"async {title}"

    spec = ServiceSpec(service=service, permissions=OPEN, validator=Titled())

    assert dispatch(spec, principal=ada, arguments={"title": "t"}).value == "async t"


# --- Pool seeds ---------------------------------------------------------------------------


def test_a_registered_seed_reaches_a_selector_that_declares_it(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=lambda *, tenant: [tenant], permissions=OPEN)

    result = dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)

    assert result.value == ["tenant-of-ada"]


def test_a_registered_seed_reaches_a_service_that_declares_it(ada: Any) -> None:
    spec = ServiceSpec(service=lambda *, tenant: tenant, permissions=OPEN)

    result = dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)

    assert result.value == "tenant-of-ada"


class _TenantValidator(Titled):
    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("tenant", "string"))


@pytest.mark.parametrize(
    ("spec", "label"),
    [
        (
            SelectorSpec(
                kind=LIST,
                selector=_returns_a_list,
                permissions=OPEN,
                reads=Parameters.of(Parameter("tenant", "string")),
            ),
            "SelectorSpec",
        ),
        (
            ServiceSpec(service=Record(), permissions=OPEN, validator=_TenantValidator(returns={})),
            "ServiceSpec",
        ),
    ],
    ids=["selector reads", "validator"],
)
def test_a_spec_declaring_a_registered_seed_s_name_is_refused(
    ada: Any, spec: Any, label: str
) -> None:
    # Optional, well-formed and open: without the registration nothing refuses it.
    dispatch(spec, principal=ada, arguments={})
    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)

    assert str(caught.value) == (
        f"{label} declares the parameter(s) ['tenant'], which a registered pool seed "
        "occupies. An argument must never meet a seed in one pool; rename the parameter."
    )


def test_a_seed_s_name_sent_as_an_argument_is_refused_as_unknown(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=lambda *, tenant: [tenant], permissions=OPEN)

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"tenant": "evil"}, pool_seeds=TENANT_SEEDS)

    assert caught.value.detail == {"tenant": ["Unknown argument."]}


def test_a_seed_s_name_sent_as_an_argument_is_dropped_under_ignore(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=lambda *, tenant: [tenant], permissions=OPEN)

    result = dispatch(
        spec,
        principal=ada,
        arguments={"tenant": "evil"},
        pool_seeds=TENANT_SEEDS,
        unknown_arguments=UnknownArguments.IGNORE,
    )

    assert result.value == ["tenant-of-ada"]


@pytest.mark.parametrize(
    ("key", "seeds"),
    [("user", DEFAULT_POOL_SEEDS), ("tenant", TENANT_SEEDS)],
    ids=["dispatcher's own", "registered"],
)
def test_a_validated_value_named_after_a_seed_is_refused(ada: Any, key: str, seeds: Any) -> None:
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, validator=Titled(returns={key: "x"}))

    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(spec, principal=ada, arguments={"title": "t"}, pool_seeds=seeds)

    assert str(caught.value) == (
        f"The Validator returned the key(s) ['{key}'], which dispatch seeds itself. A "
        "validated value must never outrank a seeded one; rename the value."
    )
    assert service.calls == []


def test_a_seed_resolves_from_the_principal_and_never_sees_an_argument(ada: Any) -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(seen=lambda **pool: sorted(pool))
    selector = Record(returns=None)
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=Titled(),
        instance_selector_spec=nested(RETRIEVE, selector=selector, reads=PK, allow_none=True),
    )

    dispatch(spec, principal=ada, arguments={"pk": 1, "title": "t"}, pool_seeds=seeds)

    assert selector.calls[0]["seen"] == ["progress", "user"]
    assert service.calls[0]["seen"] == ["progress", "user"]


def test_a_parameter_may_share_a_name_with_base_pool_s_own_keywords(ada: Any) -> None:
    reads = Parameters.of(Parameter("seeds", "integer"))
    spec = SelectorSpec(kind=LIST, selector=lambda *, seeds: [seeds], reads=reads, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={"seeds": 3}).value == [3]


def test_authorize_is_what_refuses_an_undeclared_spec(ada: Any) -> None:
    # Dispatch adds no second policy: the refusal is authorize's own, word for word.
    spec = SelectorSpec(kind=LIST, selector=_returns_a_list)
    with pytest.raises(ImproperlyConfigured) as expected:
        authorize(spec, ada)

    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert str(caught.value) == str(expected.value)


def _user_by_pk(*, pk: int) -> Any:
    return get_user_model()._default_manager.filter(pk=pk)


@pytest.mark.django_db
def test_a_service_s_target_is_presented_with_the_relations_it_wrote() -> None:
    # The instance selector prefetches the notes; the service adds one and
    # returns its target. Without clearing the target's prefetch cache, the
    # value would still list the notes as they were before the write.
    owner = make_user("prolific")
    Note.objects.create(owner=owner, title="first")

    def add_note(*, instance: Any, title: str) -> Any:
        Note.objects.create(owner=instance, title=title)
        return instance

    spec = ServiceSpec(
        service=add_note,
        permissions=OPEN,
        validator=Titled(),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_user_by_pk,
            reads=PK,
            prefetch_related=["notes"],
        ),
    )
    outcome = dispatch(spec, principal=owner, arguments={"pk": owner.pk, "title": "second"})
    assert sorted(note.title for note in outcome.value.notes.all()) == ["first", "second"]


# --- The deactivated principal ----------------------------------------------------------


def _deactivated(username: str) -> Any:
    user = make_user(username)
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


class _AskedRefuse(Refuse):
    """``Refuse``, recording every principal it was asked about."""

    def __init__(self) -> None:
        self.asked: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.asked.append(principal)
        return False


@pytest.mark.parametrize("kind", ["selector", "service"])
def test_a_deactivated_principal_is_refused_before_the_class_level_check(kind: str) -> None:
    # The class-level check would refuse too, in words of its own; it is never asked.
    check = _AskedRefuse()
    spec: SelectorSpec | ServiceSpec = (
        SelectorSpec(kind=LIST, selector=notes_of, permissions=[check])
        if kind == "selector"
        else ServiceSpec(service=Record(), permissions=[check])
    )

    with pytest.raises(PrincipalUnavailable) as caught:
        dispatch(spec, principal=_deactivated("ada"), arguments={})

    assert caught.value.message == "The acting principal is unavailable."
    assert check.asked == []


def test_a_grant_does_not_admit_a_deactivated_principal() -> None:
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN)
    who = _deactivated("ada")

    with pytest.raises(PrincipalUnavailable):
        dispatch(spec, principal=who, arguments={}, grant=Grant(spec, who, target_checked=True))

    assert service.calls == []


def test_a_deactivated_principal_is_refused_before_its_arguments_are_checked() -> None:
    # ``pk`` is missing, which the shape check would refuse; the principal answers
    # first, as ``adispatch`` refuses a deactivated ``principal_id`` and the HTTP
    # entry points a deactivated ``request.user``.
    with pytest.raises(PrincipalUnavailable):
        dispatch(retrieve(), principal=_deactivated("ada"), arguments={})


def test_anonymous_goes_on_to_the_permission_check() -> None:
    # ``AnonymousUser.is_active`` is false, so only the ``is_authenticated`` half
    # of the rule keeps this from being refused as deactivated.
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=[Refuse()])

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=AnonymousUser(), arguments={})

    assert caught.value.message == "Only editors may run this."


def test_a_principal_with_no_is_active_reads_as_active() -> None:
    principal = SimpleNamespace(is_authenticated=True)
    spec = ServiceSpec(service=lambda *, user: user, permissions=OPEN)

    assert dispatch(spec, principal=principal, arguments={}).value is principal


# --- Affordances ------------------------------------------------------------------------

NOT_ARCHIVED = Affordance(
    code="note_archived", reason="An archived note cannot be renamed.", when=Q(archived=False)
)


class _Condition:
    """A callable affordance condition answering ``returns``; records each call's keywords."""

    def __init__(self, returns: bool) -> None:
        self.returns = returns
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, user: Any) -> bool:
        self.calls.append({"user": user})
        return self.returns


def _renaming(service: Any, *affordances: Affordance, **kwargs: Any) -> ServiceSpec:
    kwargs.setdefault("permissions", [OwnerOnly()])
    kwargs.setdefault("validator", Titled())
    return ServiceSpec(
        service=service,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        affordances=list(affordances),
        **kwargs,
    )


@pytest.mark.parametrize("granted", [False, True], ids=["checked", "granted"])
def test_an_unmet_affordance_refuses_the_call_and_the_service_never_runs(
    ada: Any, granted: bool
) -> None:
    note = Note.objects.create(owner=ada, title="old", archived=True)
    service = Record()
    spec = _renaming(service, NOT_ARCHIVED)
    # A grant that claims both checks ran still leaves the row's state to ask.
    grant = Grant(spec, ada, target_checked=True) if granted else None

    with pytest.raises(ActionUnavailable) as caught:
        dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "new"}, grant=grant)

    assert (caught.value.code, caught.value.message) == (
        "note_archived",
        "An archived note cannot be renamed.",
    )
    assert service.calls == []


def test_a_met_affordance_lets_the_service_run(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="old")
    spec = _renaming(Record(returns="ran"), NOT_ARCHIVED)

    assert dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "new"}).value == "ran"


def test_the_object_level_check_answers_before_an_affordance(ada: Any, bob: Any) -> None:
    # Both would refuse: the row is archived and is not ada's. A principal who may
    # not see the row is never told what state it is in.
    theirs = Note.objects.create(owner=bob, title="theirs", archived=True)
    condition = _Condition(returns=False)
    spec = _renaming(
        Record(),
        Affordance(code="closed", reason="Closed for the night.", when=condition),
        NOT_ARCHIVED,
    )

    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk, "title": "new"})

    assert caught.value.message == "Only the owner may touch this note."
    assert condition.calls == []


class _RefusesBad(Titled):
    """``Titled``, refusing the well-shaped title ``"bad"`` as only a Validator can."""

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        if arguments["title"] == "bad":
            raise InvalidArguments({"title": ["Not that one."]})
        return super().validate(arguments, context)


def test_the_validator_answers_before_an_affordance(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="old", archived=True)
    condition = _Condition(returns=False)
    spec = _renaming(
        Record(),
        Affordance(code="closed", reason="Closed for the night.", when=condition),
        validator=_RefusesBad(),
    )

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "bad"})

    assert caught.value.detail == {"title": ["Not that one."]}
    assert condition.calls == []


def test_a_missing_row_is_not_found_and_no_affordance_is_asked(ada: Any) -> None:
    condition = _Condition(returns=False)
    spec = _renaming(
        Record(), Affordance(code="closed", reason="Closed for the night.", when=condition)
    )

    result = dispatch(spec, principal=ada, arguments={"pk": 404, "title": "new"})

    assert result.kind == "not_found"
    assert condition.calls == []


# A registered seed under the name an HTTP adapter registers its request by.
_REQUEST = object()
REQUEST_SEEDS = DEFAULT_POOL_SEEDS.extend(request=lambda: _REQUEST)


def test_a_condition_reads_a_registered_seed_through_dispatch(ada: Any) -> None:
    seen: list[Any] = []

    def from_the_request(*, request: Any) -> bool:
        seen.append(request)
        return False

    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        affordances=[Affordance(code="closed", reason="Closed.", when=from_the_request)],
    )

    with pytest.raises(ActionUnavailable):
        dispatch(spec, principal=ada, arguments={}, pool_seeds=REQUEST_SEEDS)

    assert seen == [_REQUEST]
    assert service.calls == []


def test_affordances_are_answered_before_the_transaction_opens(ada: Any) -> None:
    # Where djangorestframework-services answers them: outside the atomic block
    # ``run_service`` opens, so a refusal never opens a transaction. Depth is
    # counted, because the test's own transaction is already open around both.
    depths: dict[str, int] = {}

    def condition(*, user: Any) -> bool:
        depths["condition"] = len(connection.atomic_blocks)
        return True

    def service(*, user: Any) -> None:
        depths["service"] = len(connection.atomic_blocks)

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        atomic=True,
        affordances=[Affordance(code="open", reason="Closed.", when=condition)],
    )

    dispatch(spec, principal=ada, arguments={})

    assert depths["condition"] + 1 == depths["service"]


def test_a_selector_spec_s_affordances_are_answers_not_refusals(ada: Any) -> None:
    # A selector spec's ``affordances`` name the operations each row answers for,
    # and what a list reports is per row. Nothing about reading is refused.
    archived = Note.objects.create(owner=ada, title="old", archived=True)
    spec = SelectorSpec(
        kind=RETRIEVE,
        selector=note_by_pk,
        reads=PK,
        permissions=OPEN,
        affordances={"rename": _renaming(Record(), NOT_ARCHIVED)},
    )

    assert dispatch(spec, principal=ada, arguments={"pk": archived.pk}).value == archived


# --- Progress ---------------------------------------------------------------------------


class _Reporter:
    """A ``ProgressReporter`` that keeps every report it was given, in order."""

    def __init__(self) -> None:
        self.reports: list[tuple[float, float | None, str | None, Any]] = []

    def __call__(
        self,
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.reports.append((progress, total, message, meta))


def _exporting(*, progress: Any) -> str:
    progress(1, total=2, message="half", meta={"com.example/stage": "rows"})
    progress(2, total=2)
    return "exported"


def test_a_service_that_declares_progress_reports_to_the_caller_s_reporter(ada: Any) -> None:
    reporter = _Reporter()
    spec = ServiceSpec(service=_exporting, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={}, progress=reporter).value == "exported"
    assert reporter.reports == [
        (1, 2, "half", {"com.example/stage": "rows"}),
        (2, 2, None, None),
    ]


def test_a_service_that_declares_progress_runs_with_no_reporter_supplied(ada: Any) -> None:
    spec = ServiceSpec(service=_exporting, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={}).value == "exported"


def test_a_selector_spec_may_report_too(ada: Any) -> None:
    reporter = _Reporter()

    def counted(*, user: Any, progress: Any) -> Any:
        progress(1, message="counted")
        return Note.objects.filter(owner=user)

    spec = SelectorSpec(kind=LIST, selector=counted, permissions=OPEN)

    dispatch(spec, principal=ada, arguments={}, progress=reporter)

    assert reporter.reports == [(1, None, "counted", None)]


def test_a_lookup_never_reports_to_the_caller_s_reporter(ada: Any) -> None:
    # A target or output selector has no progress of its own to report, and one
    # reporting after the service finished would read as the work restarting.
    note = Note.objects.create(owner=ada, title="old")
    reporter = _Reporter()

    def looked_up(*, pk: int, progress: Any) -> Any:
        progress(99, message="target")
        return Note.objects.filter(pk=pk)

    def reread(*, result: Any, progress: Any) -> Any:
        progress(99, message="output")
        return Note.objects.filter(pk=result.pk)

    def rename(*, instance: Note, progress: Any) -> Note:
        progress(1, message="service")
        return instance

    spec = ServiceSpec(
        service=rename,
        permissions=OPEN,
        instance_selector_spec=nested(RETRIEVE, selector=looked_up, reads=PK),
        output_selector_spec=nested(RETRIEVE, selector=reread),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": note.pk}, progress=reporter)

    assert result.value == note
    assert reporter.reports == [(1, None, "service", None)]


def test_the_run_and_a_condition_are_handed_the_caller_s_reporter_as_it_is(ada: Any) -> None:
    # Not wrapped: a transport's reporter must not raise, because nothing
    # between it and the service would catch it.
    reporter = _Reporter()
    handed: dict[str, Any] = {}

    def condition(*, progress: Any) -> bool:
        handed["condition"] = progress
        return True

    def service(*, progress: Any) -> None:
        handed["service"] = progress

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        affordances=[Affordance(code="open", reason="Closed.", when=condition)],
    )

    dispatch(spec, principal=ada, arguments={}, progress=reporter)

    assert handed["condition"] is reporter
    assert handed["service"] is reporter


def test_an_output_selector_s_rows_are_answered_with_the_registered_seeds(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Draft")
    mine = ServiceSpec(
        service=lambda: None,
        permissions=OPEN,
        affordances=[
            Affordance(code="c", reason="r", when=lambda *, tenant: tenant == "tenant-of-ada")
        ],
    )
    spec = ServiceSpec(
        service=lambda: note.pk,
        permissions=OPEN,
        output_selector_spec=SelectorSpec(
            kind=RETRIEVE,
            selector=lambda *, result: Note.objects.filter(pk=result),
            affordances={"x": mine},
        ),
    )

    result = dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)

    assert result.value.affordance__x__c is True


# --- A parameter nothing filled -------------------------------------------------------------

TENANT_READ = Parameters.of(Parameter("tenant", "string"))
"""An optional read: the caller may leave ``tenant`` out, and nothing refuses it before the call."""

REQUIRED = ["This field is required."]
"""The shape check's own wording for a missing argument, keyed by the field it names."""


def _by_tenant(*, tenant: str) -> list[str]:
    return [tenant]


class _OptionalTitle(Validator):
    """Declares ``title`` optional and hands back exactly what it was sent."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string"))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


TITLE_READ = Parameters.of(Parameter("title", "string"))


def _titled(*, queryset: Any, title: str) -> Any:
    return queryset.filter(title=title)


def _taking_title(taker: str) -> SelectorSpec:
    """A list of notes reading an optional ``title``, taken by ``taker``."""
    if taker == "selector":
        return SelectorSpec(
            kind=LIST,
            selector=lambda *, title: Note.objects.filter(title=title),
            reads=TITLE_READ,
            permissions=OPEN,
        )
    return SelectorSpec(
        kind=LIST,
        selector=lambda: Note.objects.all(),
        extend_queryset=_titled,
        reads=TITLE_READ,
        permissions=OPEN,
    )


def test_an_optional_read_a_selector_requires_is_refused_when_not_sent(ada: Any) -> None:
    spec = SelectorSpec(kind=LIST, selector=_by_tenant, reads=TENANT_READ, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={"tenant": "acme"}).value == ["acme"]
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"tenant": REQUIRED}


def test_a_target_selector_s_unfilled_parameter_is_refused_before_it_runs(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        collection_selector_spec=nested(LIST, selector=_by_tenant, reads=TENANT_READ),
    )

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"tenant": REQUIRED}
    assert service.calls == []


def test_a_service_parameter_its_validator_left_unfilled_is_refused(ada: Any) -> None:
    calls: list[str] = []

    def rename(*, title: str) -> str:
        calls.append(title)
        return title

    spec = ServiceSpec(service=rename, permissions=OPEN, validator=_OptionalTitle())

    assert dispatch(spec, principal=ada, arguments={"title": "new"}).value == "new"
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"title": REQUIRED}
    assert calls == ["new"]


def test_a_registered_seed_fills_a_parameter_no_argument_did(ada: Any) -> None:
    """``tenant`` is not a read, so only the declaration can fill it: a
    registered seed does, and without one the call raises as the author's
    error, since no argument a caller sends could fill it."""
    spec = SelectorSpec(kind=LIST, selector=_by_tenant, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS).value == [
        "tenant-of-ada"
    ]
    with pytest.raises(TypeError, match="tenant"):
        dispatch(spec, principal=ada, arguments={})


def test_a_selector_parameter_no_read_declares_is_the_author_s_error(ada: Any) -> None:
    """The argument set is closed: ``tenant`` is not a read, so REJECT refuses
    it as unknown and IGNORE drops it, and no caller can ever fill it. Refused
    as a missing argument, the call would ask for a value nobody can send, and
    a client reading ``InvalidArguments`` as its own mistake would retry it."""
    spec = SelectorSpec(kind=LIST, selector=_by_tenant, permissions=OPEN)

    with pytest.raises(InvalidArguments) as unknown:
        dispatch(spec, principal=ada, arguments={"tenant": "acme"})
    with pytest.raises(TypeError, match="tenant"):
        dispatch(spec, principal=ada, arguments={})
    with pytest.raises(TypeError, match="tenant"):
        dispatch(
            spec,
            principal=ada,
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.IGNORE,
        )

    assert "tenant" in str(unknown.value.detail)
    assert "This field is required." not in str(unknown.value.detail)


@pytest.mark.parametrize("validator", [None, _OptionalTitle()], ids=["none", "not declaring it"])
def test_a_service_parameter_no_validator_declares_is_the_author_s_error(
    ada: Any, validator: Validator | None
) -> None:
    """Only a Validator's parameters reach the service, so a service parameter
    it does not declare - or any, with no Validator - is one no caller can fill."""
    calls: list[str] = []

    def publish(*, title: str = "", body: str) -> str:
        calls.append(body)
        return body

    spec = ServiceSpec(service=publish, permissions=OPEN, validator=validator)

    with pytest.raises(TypeError, match="body"):
        dispatch(spec, principal=ada, arguments={})
    assert calls == []


def test_a_defaulted_parameter_is_never_missing(ada: Any) -> None:
    def by_tenant(*, tenant: str = "everyone") -> list[str]:
        return [tenant]

    spec = SelectorSpec(kind=LIST, selector=by_tenant, reads=TENANT_READ, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={}).value == ["everyone"]


def test_a_callable_taking_the_whole_pool_is_never_missing_anything(ada: Any) -> None:
    """``**tenant`` is named after a read the caller left out, so only its kind
    keeps it from being refused: it takes whatever arrives, and needs nothing."""
    spec = SelectorSpec(
        kind=LIST, selector=lambda **tenant: sorted(tenant), reads=TENANT_READ, permissions=OPEN
    )

    assert dispatch(spec, principal=ada, arguments={}).value == ["progress", "user"]


def test_a_positional_only_parameter_is_not_reported(ada: Any) -> None:
    """Dispatch passes keywords only, so no caller value could ever fill it,
    even one sent under a read's name, and refusing it would ask for one."""

    def by_tenant(tenant: str, /) -> list[str]:
        return [tenant]

    spec = SelectorSpec(kind=LIST, selector=by_tenant, reads=TENANT_READ, permissions=OPEN)

    with pytest.raises(TypeError, match="tenant"):
        dispatch(spec, principal=ada, arguments={})


def test_a_var_positional_parameter_is_never_missing(ada: Any) -> None:
    """``*tenant`` is named after a read the caller left out, and is filled by
    nothing whatever is sent: it needs no value, so there is nothing to refuse."""

    def by_tenant(*tenant: str) -> list[str]:
        return list(tenant)

    spec = SelectorSpec(kind=LIST, selector=by_tenant, reads=TENANT_READ, permissions=OPEN)

    assert dispatch(spec, principal=ada, arguments={}).value == []


def test_a_missing_reserved_seed_is_the_author_s_error_and_not_refused(ada: Any) -> None:
    """``instance`` is never in a selector spec's pool, and no caller could
    send it: refusing it as a missing argument would blame the caller for a
    declaration only its author can fix."""
    spec = SelectorSpec(kind=LIST, selector=lambda *, instance: [instance], permissions=OPEN)

    with pytest.raises(TypeError, match="instance"):
        dispatch(spec, principal=ada, arguments={})


def test_an_output_selector_is_never_refused_after_the_run(ada: Any) -> None:
    """Its pool carries no argument, so nothing a caller left out can be
    missing from it, and the service has already run: a refusal that reads as
    "before the run" would tell the caller the operation did not happen."""
    service = Record(returns=1)
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        # A read declared, so that only its being after the run keeps it unrefused.
        output_selector_spec=nested(LIST, selector=_by_tenant, reads=TENANT_READ),
    )

    with pytest.raises(TypeError, match="tenant"):
        dispatch(spec, principal=ada, arguments={})
    assert len(service.calls) == 1


def test_an_output_selector_s_extend_queryset_is_never_refused_after_the_run(ada: Any) -> None:
    service = Record(returns=1)
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        output_selector_spec=nested(
            LIST,
            selector=lambda: Note.objects.all(),
            reads=TITLE_READ,
            extend_queryset=_titled,
        ),
    )

    with pytest.raises(TypeError, match="title"):
        dispatch(spec, principal=ada, arguments={})
    assert len(service.calls) == 1


@pytest.mark.parametrize("taker", ["selector", "extend_queryset"])
def test_a_read_left_out_is_refused_alike_by_whichever_callable_takes_it(
    ada: Any, taker: str
) -> None:
    """``extend_queryset`` is bound from the same pool as the selector, so a
    declared read the caller left out is the same refusal whichever one takes it."""
    Note.objects.create(owner=ada, title="kept")
    spec = _taking_title(taker)

    assert [
        note.title for note in dispatch(spec, principal=ada, arguments={"title": "kept"}).value
    ] == ["kept"]
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"title": REQUIRED}


def test_an_extend_queryset_parameter_no_read_declares_is_the_author_s_error(ada: Any) -> None:
    spec = SelectorSpec(
        kind=LIST, selector=lambda: Note.objects.all(), extend_queryset=_titled, permissions=OPEN
    )

    with pytest.raises(TypeError, match="title"):
        dispatch(spec, principal=ada, arguments={})


def test_a_target_selector_s_extend_queryset_refuses_a_read_left_out(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        collection_selector_spec=nested(
            LIST, selector=lambda: Note.objects.all(), extend_queryset=_titled, reads=TITLE_READ
        ),
    )

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})

    assert caught.value.detail == {"title": REQUIRED}
    assert service.calls == []


def test_a_missing_argument_answers_before_an_affordance(ada: Any) -> None:
    """As the Validator does: a refusal of the call itself comes before one
    describing the row's state."""
    note = Note.objects.create(owner=ada, title="old", archived=True)
    spec = _renaming(lambda *, instance, title: title, NOT_ARCHIVED, validator=_OptionalTitle())

    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"pk": note.pk})

    assert caught.value.detail == {"title": REQUIRED}
