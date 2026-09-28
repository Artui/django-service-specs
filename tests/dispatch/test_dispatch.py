from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import F, Value
from django.db.models.functions import Concat

from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments
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

    assert selector.calls == [{"user": ada, "q": "x"}]


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

    assert service.calls == [{"user": ada, "data": {"title": "Hello"}, "title": "Hello"}]
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
        {"user": ada, "data": {"title": "new"}, "title": "new", "instance": note}
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

    assert selector.calls == [{"user": ada, "pk": 7}]


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

    assert service.calls == [{"user": ada, "data": {}, "instance": None}]
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
    assert set(pool) == {"user", "data", "collection"}
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

    assert reread.calls == [{"user": ada, "result": note}]
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

    assert selector.calls[0]["seen"] == ["user"]
    assert service.calls[0]["seen"] == ["user"]


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
