from __future__ import annotations

import functools
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import F, Q, Value
from django.db.models.functions import Concat
from django.test import override_settings
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import expected_type
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import kernel_spec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import (
    OPEN,
    PK,
    TENANT_SEEDS,
    OwnerOnly,
    Record,
    Refuse,
    Scoped,
    Titled,
    Titles,
    make_user,
    note_by_pk,
    notes_of,
    shaping_refused,
)
from tests.dispatch_app.models import Note
from tests.parameters.utils import coded
from tests.specs.utils import Bare, Foreign

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


def test_a_grant_that_checked_a_target_does_not_cover_the_row_a_selector_spec_finds(
    ada: Any, bob: Any
) -> None:
    # A selector spec takes no ``target=``, so a grant has no row to be bound
    # to: whatever its transport checked, the row the arguments make the
    # selector find is checked here, as a service spec's lookup is.
    theirs = Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()
    spec = retrieve(permissions=[check])
    grant = Grant(spec, ada, target_checked=True)

    with pytest.raises(NotPermitted):
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk}, grant=grant)

    assert check.rows == [theirs]


def test_a_grant_that_checked_a_target_does_not_cover_the_set_a_selector_spec_reads(
    ada: Any,
) -> None:
    Note.objects.create(owner=ada, title="mine")
    check = Scoped(refuse_scope=True)
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=[check])
    grant = Grant(spec, ada, target_checked=True)

    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={}, grant=grant)

    assert len(check.scopes) == 1


def test_a_selector_spec_s_object_level_check_sees_the_row_the_call_returns(ada: Any) -> None:
    # The row after shaping and the collapse to one row: the very object the
    # result carries, annotations included, never the queryset it came from.
    mine = Note.objects.create(owner=ada, title="mine")
    check = OwnerOnly()
    spec = retrieve(permissions=[check], annotations={"shaped": Value(1)})

    result = dispatch(spec, principal=ada, arguments={"pk": mine.pk})

    assert check.rows == [result.value]
    assert check.rows[0] is result.value
    assert check.rows[0].shaped == 1


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


def test_the_output_selector_re_reads_with_only_the_service_s_return_in_its_pool(ada: Any) -> None:
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

    assert reread.calls == [
        {"user": ada, "progress": null_progress, "instance": note, "result": note}
    ]
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


def test_an_output_selector_reads_the_service_s_return_as_instance_not_the_target(
    ada: Any,
) -> None:
    # The service acts on one note and returns another, so a re-read handed
    # the resolved target under ``instance`` would answer the wrong row.
    target = Note.objects.create(owner=ada, title="target")
    written = Note.objects.create(owner=ada, title="written")

    def reread(*, instance: Any) -> Any:
        return Note.objects.filter(pk=instance.pk)

    spec = ServiceSpec(
        service=Record(returns=written),
        permissions=OPEN,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        output_selector_spec=nested(RETRIEVE, selector=reread),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": target.pk})

    assert (result.kind, result.value, result.instance) == ("instance", written, target)


@pytest.mark.parametrize("returns", [None, ["a", "b"], "done"], ids=["none", "list", "str"])
def test_an_output_selector_s_instance_and_result_are_one_value(ada: Any, returns: Any) -> None:
    # One pool entry under two names, whatever the service returned: a re-read
    # declares whichever its author wrote, as under djangorestframework-services.
    reread = Record(returns=Note.objects.none())
    spec = ServiceSpec(
        service=Record(returns=returns),
        permissions=OPEN,
        output_selector_spec=nested(RETRIEVE, selector=reread),
    )

    dispatch(spec, principal=ada, arguments={})

    (pool,) = reread.calls
    assert pool["instance"] is returns
    assert pool["result"] is returns


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
    # A grant that claims both checks ran, on the row handed over with it,
    # still leaves the row's state to ask.
    extra: dict[str, Any] = (
        {"grant": Grant(spec, ada, target_checked=True), "target": note} if granted else {}
    )

    with pytest.raises(ActionUnavailable) as caught:
        dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "new"}, **extra)

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


def test_a_read_a_selector_asks_for_and_nothing_fills_carries_the_required_code(ada: Any) -> None:
    # The shape check's own code for the same absence, so a caller reads one
    # code whichever of the two refused the read.
    spec = SelectorSpec(kind=LIST, selector=_by_tenant, reads=TENANT_READ, permissions=OPEN)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert coded(caught.value.detail) == {"tenant": [("This field is required.", "required")]}


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


class _ConfirmedForm(forms.Form):
    """Checks ``confirm`` in ``clean()`` and pops it, as a confirmation field is
    popped: it is the form's to read, and never reaches the service."""

    confirm = forms.BooleanField()

    def clean(self) -> dict[str, Any]:
        self.cleaned_data.pop("confirm")
        return self.cleaned_data


class _Due(BaseModel):
    due_date: str = Field(alias="dueDate")


class _DropsTitle(Validator):
    """Declares ``title`` and hands back nothing of what it was sent."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string"))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return {}


def _confirm(*, confirm: bool) -> bool:
    return confirm


def _schedule(*, dueDate: str) -> str:
    return dueDate


def _rename(*, title: str) -> str:
    return title


@pytest.mark.parametrize(
    ("validator", "service", "arguments", "name"),
    [
        (FormValidator(_ConfirmedForm), _confirm, {"confirm": True}, "confirm"),
        (PydanticValidator(_Due), _schedule, {"dueDate": "2026-10-06"}, "dueDate"),
        (_DropsTitle(), _rename, {"title": "new"}, "title"),
    ],
    ids=["a form popping it in clean", "a pydantic alias", "a validator dropping it"],
)
def test_a_validator_parameter_the_caller_sent_is_the_author_s_error(
    ada: Any, validator: Validator, service: Any, arguments: dict[str, Any], name: str
) -> None:
    """The caller sent every argument, and the Validator did not hand ``name``
    back under that name: a form read it and popped it, pydantic returned it
    under the field's own name, or the Validator dropped it. Refused as missing,
    the call would tell the caller a field they just sent is required, and a
    client reading ``InvalidArguments`` as its own mistake would send it again,
    forever. It is the declaration's error, and raises as the callable's own."""
    spec = ServiceSpec(service=service, permissions=OPEN, validator=validator)

    with pytest.raises(TypeError, match=name):
        dispatch(spec, principal=ada, arguments=arguments)


def test_a_service_parameter_named_after_a_target_read_is_the_author_s_error(ada: Any) -> None:
    """``pk`` is the instance selector's read, consumed there and never in the
    service's pool, and the caller sent it: only a Validator's parameters are
    the service's to ask a caller for, never the spec's whole argument set."""
    note = Note.objects.create(owner=ada, title="mine")
    spec = ServiceSpec(
        service=lambda *, instance, pk: pk,
        permissions=OPEN,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
    )

    with pytest.raises(TypeError, match="pk"):
        dispatch(spec, principal=ada, arguments={"pk": note.pk})


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


# --- partial, the Validator's whole result, reads, providers, preconditions and
# the spec's progress provider: what dispatch does with each spec field.


class _NoteForm(forms.Form):
    title = forms.CharField()
    body = forms.CharField()


def _partial_edit(service: Any, **kwargs: Any) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=FormValidator(_NoteForm),
        partial=True,
        **kwargs,
    )


def test_a_partial_spec_dispatched_with_one_field_reaches_the_service_with_that_field_alone(
    ada: Any,
) -> None:
    service = Record()
    dispatch(_partial_edit(service), principal=ada, arguments={"title": "Kept"})
    assert service.calls[0]["data"] == {"title": "Kept"}
    assert "body" not in service.calls[0]


def test_the_same_call_without_partial_is_refused_by_the_shape_check(ada: Any) -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN, validator=FormValidator(_NoteForm))
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"title": "Kept"})
    assert caught.value.detail == {"body": ["This field is required."]}


def test_a_partial_call_tells_the_validator_it_is_partial(ada: Any) -> None:
    validator = Titled()
    spec = ServiceSpec(service=Record(), permissions=OPEN, validator=validator, partial=True)
    dispatch(spec, principal=ada, arguments={"title": " T "})
    assert validator.calls[0][1].partial is True


def test_a_partial_call_never_refuses_a_service_parameter_the_caller_left_out(ada: Any) -> None:
    # The service declaring ``body`` with no default is the author's error under
    # ``partial``, where any field may be left out: it raises as the callable's
    # own, never as a missing argument a client would be asked to resend.
    def edit(*, title: str, body: str) -> None: ...

    with pytest.raises(TypeError, match="body"):
        dispatch(_partial_edit(edit), principal=ada, arguments={"title": "Kept"})


@dataclass
class _Draft:
    title: str


def test_a_dataclass_validator_hands_the_service_its_instance_as_data(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, validator=DataclassValidator(_Draft))
    result = dispatch(spec, principal=ada, arguments={"title": "Draft"})
    assert service.calls[0]["data"] == _Draft(title="Draft")
    assert service.calls[0]["title"] == "Draft"
    assert result.data == _Draft(title="Draft")


class _Binds(Titled):
    """Binds ``bound`` for the call beside the values, as a library adapter binds its object."""

    def __init__(self, bound: Mapping[str, Any], returns: Mapping[str, Any] | None = None) -> None:
        super().__init__(returns)
        self.bound = bound

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        values = self.validate(arguments, context)
        return Validated(values=values, data=values, pool=self.bound)


def test_a_value_the_validator_binds_reaches_the_service_by_name(ada: Any) -> None:
    def create(*, title: str, form: Any) -> Any:
        return (title, form)

    marker = object()
    spec = ServiceSpec(service=create, permissions=OPEN, validator=_Binds({"form": marker}))
    result = dispatch(spec, principal=ada, arguments={"title": "T"})
    assert result.value == ("T", marker)


@pytest.mark.parametrize(
    ("bound", "named"),
    [
        pytest.param({"user": "someone"}, "['user']", id="a-seed"),
        pytest.param({"title": "other"}, "['title']", id="a-validated-value"),
        # A value the Validator returns without declaring it: no parameter
        # names it, so only the validated values' own names refuse it.
        pytest.param({"slug": "other"}, "['slug']", id="an-undeclared-validated-value"),
    ],
)
def test_a_bound_value_naming_a_seed_or_a_validated_value_is_refused(
    ada: Any, bound: Mapping[str, Any], named: str
) -> None:
    def create(*, user: Any, title: str, slug: str) -> Any:
        return (user, title, slug)

    validator = _Binds(bound, returns={"title": "T", "slug": "t"})
    spec = ServiceSpec(service=create, permissions=OPEN, validator=validator)
    with pytest.raises(ImproperlyConfigured, match=f"bound the key\\(s\\) {re.escape(named)}"):
        dispatch(spec, principal=ada, arguments={"title": "T"})


PROJECT = Parameters.of(Parameter("project_pk", "integer", required=True))


def test_a_reads_argument_reaches_the_service_and_never_the_validator(ada: Any) -> None:
    def create(*, project_pk: int, title: str) -> Any:
        return (project_pk, title)

    validator = Titled()
    spec = ServiceSpec(service=create, permissions=OPEN, reads=PROJECT, validator=validator)
    result = dispatch(spec, principal=ada, arguments={"project_pk": 7, "title": "T"})
    assert result.value == (7, "T")
    assert validator.calls[0][0] == {"title": "T"}


def test_an_optional_read_the_service_requires_is_refused_when_not_sent(ada: Any) -> None:
    def create(*, project_pk: int) -> None: ...

    spec = ServiceSpec(
        service=create,
        permissions=OPEN,
        reads=Parameters.of(Parameter("project_pk", "integer")),
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"project_pk": ["This field is required."]}


def test_a_create_s_kwargs_provider_reads_a_reads_argument(ada: Any) -> None:
    seen: list[dict[str, Any]] = []

    def scope(*, user: Any, project_pk: int) -> dict[str, Any]:
        seen.append({"user": user, "project_pk": project_pk})
        return {"scope": f"project-{project_pk}"}

    def create(*, scope: str, title: str) -> Any:
        return (scope, title)

    spec = ServiceSpec(
        service=create, permissions=OPEN, reads=PROJECT, validator=Titled(), kwargs=scope
    )
    result = dispatch(spec, principal=ada, arguments={"project_pk": 7, "title": "T"})
    assert result.value == ("project-7", "T")
    assert seen == [{"user": ada, "project_pk": 7}]


def test_a_kwargs_provider_s_value_is_the_author_s_whatever_the_caller_sent(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        reads=PROJECT,
        validator=Titled(),
        kwargs=lambda: {"title": "author's", "project_pk": 1},
    )
    result = dispatch(spec, principal=ada, arguments={"project_pk": 7, "title": "caller's"})
    assert (service.calls[0]["title"], service.calls[0]["project_pk"]) == ("author's", 1)
    # ``data`` is what the Validator validated: the provider adds pool entries.
    assert result.data == {"title": "caller's"}


def test_a_kwargs_provider_declines_a_key_with_unset(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=Titled(),
        kwargs=lambda: {"title": UNSET, "tag": "author's"},
    )
    dispatch(spec, principal=ada, arguments={"title": "caller's"})
    assert (service.calls[0]["title"], service.calls[0]["tag"]) == ("caller's", "author's")


@pytest.mark.parametrize("key", ["user", "data", "instance"])
def test_a_kwargs_provider_returning_a_seeded_key_is_refused(ada: Any, key: str) -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN, kwargs=lambda: {key: "forged"})
    with pytest.raises(ImproperlyConfigured, match="ServiceSpec.kwargs returned the key"):
        dispatch(spec, principal=ada, arguments={})


def test_input_data_is_merged_over_the_caller_s_arguments_before_the_validator(
    ada: Any,
) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    seen: list[Any] = []

    def server(*, instance: Note) -> dict[str, Any]:
        seen.append(instance)
        return {"title": f"from {instance.title}", "undeclared": 1}

    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        input_data=server,
    )
    dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "caller's"})
    assert seen == [note]
    # Only what the Validator declares is handed to it, the server's value winning.
    assert validator.calls[0][0] == {"title": "from Row"}


def test_input_data_declines_a_key_with_unset(ada: Any) -> None:
    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=validator,
        input_data=lambda: {"title": UNSET},
    )
    dispatch(spec, principal=ada, arguments={"title": "caller's"})
    assert validator.calls[0][0] == {"title": "caller's"}


def test_a_selector_spec_s_kwargs_provider_scopes_its_selector(ada: Any, bob: Any) -> None:
    Note.objects.create(owner=ada, title="Ada's")
    Note.objects.create(owner=bob, title="Bob's")

    def owned(*, owner: Any) -> Any:
        return Note.objects.filter(owner=owner)

    spec = SelectorSpec(
        kind=LIST, selector=owned, permissions=OPEN, kwargs=lambda user: {"owner": user}
    )
    result = dispatch(spec, principal=bob, arguments={})
    assert [note.title for note in result.value] == ["Bob's"]


def test_a_target_selector_s_kwargs_provider_scopes_the_lookup(ada: Any, bob: Any) -> None:
    note = Note.objects.create(owner=ada, title="Ada's")

    def owned(*, pk: int, owner: Any) -> Any:
        return Note.objects.filter(pk=pk, owner=owner)

    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        instance_selector_spec=nested(
            RETRIEVE, selector=owned, reads=PK, kwargs=lambda user: {"owner": user}
        ),
    )
    assert dispatch(spec, principal=bob, arguments={"pk": note.pk}).kind == "not_found"


def test_a_selector_spec_s_kwargs_provider_returning_a_seeded_key_is_refused(ada: Any) -> None:
    spec = SelectorSpec(
        kind=LIST, selector=notes_of, permissions=OPEN, kwargs=lambda: {"user": "forged"}
    )
    with pytest.raises(ImproperlyConfigured, match="SelectorSpec.kwargs returned the key"):
        dispatch(spec, principal=ada, arguments={})


class _Precondition:
    """Records the keywords it was called with, and raises ``raises`` if given."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **pool: Any) -> None:
        self.calls.append(pool)
        if self.raises is not None:
            raise self.raises


def test_a_precondition_aborts_the_call_before_the_service(ada: Any) -> None:
    service = Record()
    precondition = _Precondition(Boom())
    spec = ServiceSpec(
        service=service, permissions=OPEN, validator=Titled(), preconditions=[precondition]
    )
    with pytest.raises(Boom):
        dispatch(spec, principal=ada, arguments={"title": " T "})
    assert service.calls == []
    assert precondition.calls[0]["data"] == {"title": "T"}


def test_preconditions_run_in_declaration_order_with_the_row(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    order: list[str] = []

    def first(*, instance: Note) -> None:
        order.append(f"first {instance.title}")

    def second(*, instance: Note) -> None:
        order.append(f"second {instance.title}")

    spec = ServiceSpec(
        service=lambda: order.append("service"),
        permissions=OPEN,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        preconditions=[first, second],
    )
    dispatch(spec, principal=ada, arguments={"pk": note.pk})
    assert order == ["first Row", "second Row", "service"]


def test_an_affordance_answers_before_a_precondition(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Row", archived=True)
    precondition = _Precondition()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        affordances=[NOT_ARCHIVED],
        preconditions=[precondition],
    )
    with pytest.raises(ActionUnavailable):
        dispatch(spec, principal=ada, arguments={"pk": note.pk})
    assert precondition.calls == []


def test_a_retrieve_selector_spec_s_preconditions_run_after_the_object_check(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    precondition = _Precondition(Boom())
    with pytest.raises(Boom):
        dispatch(retrieve(preconditions=[precondition]), principal=ada, arguments={"pk": note.pk})
    assert precondition.calls[0]["instance"] == note
    assert precondition.calls[0]["pk"] == note.pk


def test_a_list_selector_spec_s_preconditions_see_the_collection(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    precondition = _Precondition()
    spec = SelectorSpec(
        kind=LIST, selector=notes_of, permissions=OPEN, preconditions=[precondition]
    )
    dispatch(spec, principal=ada, arguments={})
    assert list(precondition.calls[0]["collection"]) == [note]


def test_a_retrieve_selector_spec_s_preconditions_never_run_on_a_row_the_principal_is_refused(
    ada: Any, bob: Any
) -> None:
    # The object check answers first, so a principal refused the row is never
    # told what a rule over it says.
    theirs = Note.objects.create(owner=bob, title="theirs")
    precondition = _Precondition(Boom())
    spec = retrieve(permissions=[OwnerOnly()], preconditions=[precondition])
    with pytest.raises(NotPermitted):
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk})
    assert precondition.calls == []


def _refuses_later(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A decorator whose plain ``def`` wrapper hides the ``async def`` it wraps."""

    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> Any:
        return fn(**kwargs)

    return wrapper


@_refuses_later
async def _closed_for_the_night() -> None:
    raise Boom()


@pytest.mark.parametrize(
    "make",
    [
        lambda pre: ServiceSpec(service=Record(), permissions=OPEN, preconditions=[pre]),
        lambda pre: SelectorSpec(
            kind=LIST, selector=notes_of, permissions=OPEN, preconditions=[pre]
        ),
    ],
    ids=["service-spec", "selector-spec"],
)
def test_a_precondition_answering_with_a_coroutine_refuses_the_call(
    ada: Any, make: Callable[[Any], ServiceSpec | SelectorSpec]
) -> None:
    spec = make(_closed_for_the_night)
    with pytest.raises(ImproperlyConfigured) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert str(caught.value).startswith(
        "The precondition _closed_for_the_night answered with an awaitable (coroutine). "
        "A precondition is sync-only"
    )
    run = getattr(spec, "service", None)
    assert run is None or run.calls == []


@pytest.mark.parametrize("allow_none", [False, True])
def test_a_selector_spec_s_preconditions_never_run_without_a_row(
    ada: Any, allow_none: bool
) -> None:
    precondition = _Precondition(Boom())
    spec = retrieve(preconditions=[precondition], allow_none=allow_none)
    dispatch(spec, principal=ada, arguments={"pk": 404})
    assert precondition.calls == []


class _Sink:
    """A spec-level progress provider: records each time it is resolved, and each report."""

    def __init__(self, declines: bool = False) -> None:
        self.declines = declines
        self.resolved: list[Any] = []
        self.reports: list[float] = []

    def __call__(self, *, user: Any) -> Any:
        self.resolved.append(user)
        return None if self.declines else self.report

    def report(self, progress: float, **_: Any) -> None:
        self.reports.append(progress)


def _reporting(*, progress: Any) -> None:
    progress(0.5)
    progress(1.0)


def test_a_spec_s_progress_provider_hears_every_report_beside_the_transport_s(ada: Any) -> None:
    sink = _Sink()
    transport: list[float] = []
    spec = ServiceSpec(service=_reporting, permissions=OPEN, progress_reporter=sink)
    dispatch(spec, principal=ada, arguments={}, progress=lambda p, **_: transport.append(p))
    assert (sink.resolved, sink.reports, transport) == ([ada], [0.5, 1.0], [0.5, 1.0])


def test_a_progress_provider_returning_none_declines(ada: Any) -> None:
    transport: list[float] = []
    spec = ServiceSpec(service=_reporting, permissions=OPEN, progress_reporter=_Sink(True))
    dispatch(spec, principal=ada, arguments={}, progress=lambda p, **_: transport.append(p))
    assert transport == [0.5, 1.0]


def test_a_call_refused_before_its_run_never_calls_the_progress_provider(ada: Any) -> None:
    sink = _Sink()
    spec = ServiceSpec(
        service=_reporting,
        permissions=OPEN,
        progress_reporter=sink,
        preconditions=[_Precondition(Boom())],
    )
    with pytest.raises(Boom):
        dispatch(spec, principal=ada, arguments={})
    assert sink.resolved == []


def test_a_run_that_never_reports_never_calls_the_progress_provider(ada: Any) -> None:
    sink = _Sink()
    dispatch(
        ServiceSpec(service=Record(), permissions=OPEN, progress_reporter=sink),
        principal=ada,
        arguments={},
    )
    assert sink.resolved == []


def test_an_async_service_s_progress_provider_is_resolved_before_the_run(ada: Any) -> None:
    # A provider that queries cannot run on the loop an ``async def`` service
    # reports from, so it is resolved from sync code first.
    count: list[int] = []
    sink = _Sink()

    def querying(*, user: Any) -> Any:
        count.append(Note.objects.count())
        return sink(user=user)

    async def reporting(*, progress: Any) -> None:
        progress(1.0)

    spec = ServiceSpec(service=reporting, permissions=OPEN, progress_reporter=querying)
    dispatch(spec, principal=ada, arguments={})
    assert (count, sink.reports) == ([0], [1.0])


def test_a_selector_spec_s_progress_provider_hears_its_selector(ada: Any) -> None:
    sink = _Sink()

    def reporting(*, user: Any, progress: Any) -> Any:
        progress(1.0)
        return notes_of(user=user)

    spec = SelectorSpec(kind=LIST, selector=reporting, permissions=OPEN, progress_reporter=sink)
    dispatch(spec, principal=ada, arguments={})
    assert sink.reports == [1.0]


def test_a_selector_spec_s_precondition_reports_to_the_transport_and_not_the_spec_s_sink(
    ada: Any,
) -> None:
    # The spec's sink is the run's, and a selector spec's run is its selector:
    # a precondition answering after it reports where a service spec's does.
    sink = _Sink()
    transport: list[float] = []

    def reporting(*, user: Any, progress: Any) -> Any:
        progress(1.0)
        return notes_of(user=user)

    def checking(*, progress: Any) -> None:
        progress(0.5)

    spec = SelectorSpec(
        kind=LIST,
        selector=reporting,
        permissions=OPEN,
        progress_reporter=sink,
        preconditions=[checking],
    )
    dispatch(spec, principal=ada, arguments={}, progress=lambda p, **_: transport.append(p))
    assert (sink.reports, transport) == ([1.0], [1.0, 0.5])


def test_a_selector_spec_s_queryset_step_and_row_conditions_read_the_transport_s_reporter(
    ada: Any,
) -> None:
    # Only the selector, the run, reports to the spec's sink: what shapes its
    # rows and what answers each row's affordances are handed the reporter
    # the transport passed, as a service spec's conditions are.
    Note.objects.create(owner=ada, title="Row")
    sink = _Sink()
    reporter = _Reporter()
    handed: dict[str, Any] = {}

    def narrowing(*, queryset: Any, progress: Any) -> Any:
        handed["extend_queryset"] = progress
        return queryset

    def condition(*, progress: Any) -> bool:
        handed["condition"] = progress
        return True

    renaming = ServiceSpec(
        service=lambda: None,
        permissions=OPEN,
        affordances=[Affordance(code="open", reason="Closed.", when=condition)],
    )
    spec = SelectorSpec(
        kind=LIST,
        selector=notes_of,
        permissions=OPEN,
        extend_queryset=narrowing,
        affordances={"rename": renaming},
        progress_reporter=sink,
    )
    rows = list(dispatch(spec, principal=ada, arguments={}, progress=reporter).value)

    assert rows[0].affordance__rename__open is True
    assert handed == {"extend_queryset": reporter, "condition": reporter}
    assert sink.resolved == []


def test_a_sync_selector_calls_the_progress_provider_on_its_first_report_alone(
    ada: Any,
) -> None:
    # Bound and handed a reporter, a selector that never reports never calls
    # the provider: a sync run resolves it on the first report.
    sink = _Sink()

    def quiet(*, user: Any, progress: Any) -> Any:
        return notes_of(user=user)

    spec = SelectorSpec(kind=LIST, selector=quiet, permissions=OPEN, progress_reporter=sink)
    dispatch(spec, principal=ada, arguments={})
    assert sink.resolved == []


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_a_selector_spec_s_progress_provider_is_called_from_the_base_pool(
    ada: Any, asynchronous: bool
) -> None:
    # As a service spec's is: the seeds, never the reads the caller sent, so a
    # provider taking the whole pool sees what ``base_pool`` holds and no more.
    seen: list[list[str]] = []

    def provider(**pool: Any) -> Any:
        seen.append(sorted(pool))
        return None

    def by_title(*, user: Any, title: str, progress: Any) -> Any:
        progress(1.0)
        return notes_of(user=user)

    async def aby_title(*, user: Any, title: str, progress: Any) -> Any:
        progress(1.0)
        return notes_of(user=user)

    spec = SelectorSpec(
        kind=LIST,
        selector=aby_title if asynchronous else by_title,
        reads=Parameters.of(Parameter("title", "string")),
        permissions=OPEN,
        progress_reporter=provider,
    )
    dispatch(spec, principal=ada, arguments={"title": "Ada's"})
    assert seen == [["progress", "user"]]


def test_an_async_selector_refused_its_missing_read_never_calls_the_progress_provider(
    ada: Any,
) -> None:
    # An ``async def`` selector's provider is resolved before the run, so it
    # must be resolved after the binding that refuses a read left out, as a
    # service's is: a call refused before its run never calls it.
    sink = _Sink()

    async def by_title(*, user: Any, title: str, progress: Any) -> Any:
        return notes_of(user=user)

    spec = SelectorSpec(
        kind=LIST,
        selector=by_title,
        reads=Parameters.of(Parameter("title", "string")),
        permissions=OPEN,
        progress_reporter=sink,
    )
    with pytest.raises(InvalidArguments):
        dispatch(spec, principal=ada, arguments={})
    assert sink.resolved == []


def test_an_async_selector_that_takes_no_progress_never_calls_the_progress_provider(
    ada: Any,
) -> None:
    # As for a service: a run that could never report never calls it.
    sink = _Sink()

    async def silent(*, user: Any) -> Any:
        return notes_of(user=user)

    spec = SelectorSpec(kind=LIST, selector=silent, permissions=OPEN, progress_reporter=sink)
    dispatch(spec, principal=ada, arguments={})
    assert sink.resolved == []


def test_a_read_outranks_a_validated_value_of_its_name(ada: Any) -> None:
    # A Validator may return a key it does not declare; a read the caller sent
    # under that name is the argument, as a route's own capture outranks the body.
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        reads=PROJECT,
        validator=Titled(returns={"title": "T", "project_pk": 1}),
    )
    dispatch(spec, principal=ada, arguments={"project_pk": 7, "title": "T"})
    assert service.calls[0]["project_pk"] == 7


@pytest.mark.parametrize(
    ("bound", "partial", "arguments"),
    [
        pytest.param({"project_pk": 1}, False, {"project_pk": 7, "title": "T"}, id="a-read"),
        pytest.param(
            {"body": "bound"}, True, {"project_pk": 7, "title": "T"}, id="a-field-left-out"
        ),
    ],
)
def test_a_bound_value_naming_a_parameter_is_refused(
    ada: Any, bound: Mapping[str, Any], partial: bool, arguments: Mapping[str, Any]
) -> None:
    # A bound value is not one the caller sent, so it may not stand in for an
    # argument the caller sends or, under ``partial``, chose to leave out.
    class _BindsBody(_Binds):
        def parameters(self) -> Parameters:
            return super().parameters() + Parameters.of(Parameter("body", "string"))

    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        reads=PROJECT,
        validator=_BindsBody(bound),
        partial=partial,
    )
    with pytest.raises(ImproperlyConfigured, match="bound the key"):
        dispatch(spec, principal=ada, arguments=arguments)


def test_an_async_run_refused_before_it_starts_never_calls_the_progress_provider(
    ada: Any,
) -> None:
    # The provider of an ``async def`` run is resolved before the run, so it
    # must be resolved after everything that can refuse the call.
    sink = _Sink()

    async def reporting(*, progress: Any) -> None:
        progress(1.0)

    spec = ServiceSpec(
        service=reporting,
        permissions=OPEN,
        progress_reporter=sink,
        preconditions=[_Precondition(Boom())],
    )
    with pytest.raises(Boom):
        dispatch(spec, principal=ada, arguments={})
    assert sink.resolved == []


# --- what the shape check may leave out: under ``partial``, the Validator's
# fields alone; and a field the spec's ``input_data`` provider fills.


def _refused_at_the_shape_check(spec: ServiceSpec, principal: Any, arguments: Any) -> Any:
    """The shape check's refusal, where a class-level refusal would answer next.

    Each spec here refuses every principal at class level, so a call the shape
    check lets through is refused as ``NotPermitted`` instead. Without that, an
    argument the shape check leaves out is refused one step later in the same
    words, by the selector or the service that asks for it.
    """
    with pytest.raises(DispatchError) as caught:
        dispatch(spec, principal=principal, arguments=arguments)
    assert isinstance(caught.value, InvalidArguments), caught.value
    return caught.value.detail


def test_a_partial_call_omitting_a_read_is_refused_at_the_shape_check(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        reads=PROJECT,
        validator=FormValidator(_NoteForm),
        partial=True,
    )
    assert _refused_at_the_shape_check(spec, ada, {"title": "Kept"}) == {"project_pk": REQUIRED}


def test_a_partial_call_omitting_the_target_s_pk_is_refused_at_the_shape_check(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        validator=FormValidator(_NoteForm),
        partial=True,
    )
    assert _refused_at_the_shape_check(spec, ada, {"title": "Kept"}) == {"pk": REQUIRED}


class _Echo(Validator):
    """Declares ``parameters`` and hands back what it was sent: the shape check's own subject."""

    def __init__(self, parameters: Parameters) -> None:
        self._parameters = parameters

    def parameters(self) -> Parameters:
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def test_a_partial_call_may_leave_out_a_validator_field_at_every_depth(ada: Any) -> None:
    # ``tone`` is required with a default, which a relaxed copy must keep
    # constructing: the declaration is rebuilt for the shape check.
    row = Parameters.of(
        Parameter("title", "string", required=True),
        Parameter("tone", "string", required=True, default="plain"),
    )
    declared = Parameters.of(
        Parameter("rows", "array", required=True, items=row),
        Parameter("meta", "object", required=True, fields=row),
        Parameter("tags", "array", items="string"),
    )
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, validator=_Echo(declared), partial=True)
    arguments = {"rows": [{}], "meta": {}, "tags": ["a"]}
    dispatch(spec, principal=ada, arguments=arguments)
    assert service.calls[0]["data"] == arguments
    # A present value is still checked, and an unknown key still refused, below
    # the top as at it.
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"rows": [{"title": 1, "x": 2}]})
    assert caught.value.detail == {
        "rows": {0: {"title": ["Expected a string."], "x": ["Unknown argument."]}}
    }


class _ServerTitle(TypedDict):
    title: str


def _title_provider(title: Any = "server's") -> tuple[Callable[[], _ServerTitle], list[None]]:
    """An ``input_data`` provider annotated to fill ``title``, and the list its calls append to.

    A function rather than a recording object: ``provider_keys`` reads a
    function's return annotation.
    """
    calls: list[None] = []

    def server() -> _ServerTitle:
        calls.append(None)
        return {"title": title}

    return server, calls


def test_an_input_data_provider_fills_a_required_validator_field_the_caller_left_out(
    ada: Any,
) -> None:
    validator = Titled()
    spec = ServiceSpec(
        service=Record(), permissions=OPEN, validator=validator, input_data=_title_provider()[0]
    )
    dispatch(spec, principal=ada, arguments={})
    assert validator.calls[0][0] == {"title": "server's"}


def test_a_filled_field_the_provider_declines_is_refused_by_the_validator(ada: Any) -> None:
    provider, calls = _title_provider(title=UNSET)

    class _TitleForm(forms.Form):
        title = forms.CharField()

    spec = ServiceSpec(
        service=Record(), permissions=OPEN, validator=FormValidator(_TitleForm), input_data=provider
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"title": REQUIRED}
    # The Validator answered, since the shape check let the field through: the
    # provider ran, and it runs after the shape check.
    assert calls == [None]


def test_a_field_the_provider_does_not_name_stays_required(ada: Any) -> None:
    provider, calls = _title_provider()
    spec = ServiceSpec(
        service=Record(), permissions=OPEN, validator=FormValidator(_NoteForm), input_data=provider
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"body": REQUIRED}
    assert calls == []


def test_an_untyped_input_data_provider_relaxes_nothing(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=Titled(),
        input_data=lambda: {"title": "server's"},
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"title": REQUIRED}


# A ``kwargs`` provider annotated to fill a read: the spec's own reaches the
# service, and a selector's own reaches that selector, so a caller is not asked
# for what the provider answers. Each provider relaxes only the parameters its
# values reach; one filling a parameter its values never reach is refused when
# the spec is built (TestProviderReach in tests/specs/test_service_spec.py).


class _ServerProjectPk(TypedDict):
    project_pk: int


class _ServerPk(TypedDict):
    pk: int


class _ServerTenant(TypedDict):
    tenant: str


_OMITTED = object()
"""Handed to a provider factory to make the provider leave its key out altogether."""


def _project_provider(project_pk: Any = 7) -> tuple[Callable[[], _ServerProjectPk], list[None]]:
    """A ``kwargs`` provider annotated to fill ``project_pk``, and the list its calls append to."""
    calls: list[None] = []

    def server() -> _ServerProjectPk:
        calls.append(None)
        return {} if project_pk is _OMITTED else {"project_pk": project_pk}

    return server, calls


def _pk_provider(pk: Any) -> tuple[Callable[[], _ServerPk], list[None]]:
    """A selector's ``kwargs`` provider annotated to fill ``pk``, and the list its calls append to."""
    calls: list[None] = []

    def server() -> _ServerPk:
        calls.append(None)
        return {} if pk is _OMITTED else {"pk": pk}

    return server, calls


def test_a_read_the_spec_s_kwargs_provider_fills_is_not_demanded_of_the_caller(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=PROJECT, kwargs=_project_provider()[0]
    )
    dispatch(spec, principal=ada, arguments={})
    assert service.calls[0]["project_pk"] == 7


def test_a_relaxed_read_the_caller_sends_is_still_checked_and_the_provider_outranks_it(
    ada: Any,
) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=PROJECT, kwargs=_project_provider()[0]
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"project_pk": "x"})
    assert caught.value.detail == {"project_pk": ["Expected an integer."]}
    dispatch(spec, principal=ada, arguments={"project_pk": 1})
    assert service.calls[0]["project_pk"] == 7


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_filled_read_the_provider_declines_is_refused_where_the_service_asks_for_it(
    ada: Any, declined: Any
) -> None:
    # Required of what the service is called with, not of the caller: the
    # refusal is the usual one, from ``call_keywords``, after the provider ran.
    provider, calls = _project_provider(project_pk=declined)
    ran: list[int] = []

    def create(*, project_pk: int) -> None:
        ran.append(project_pk)

    spec = ServiceSpec(service=create, permissions=OPEN, reads=PROJECT, kwargs=provider)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"project_pk": REQUIRED}
    assert calls == [None]
    assert ran == []


def test_a_read_the_provider_does_not_name_stays_required(ada: Any) -> None:
    def server() -> _ServerTenant:
        return {"tenant": "t"}

    spec = ServiceSpec(service=Record(), permissions=[Refuse()], reads=PROJECT, kwargs=server)
    assert _refused_at_the_shape_check(spec, ada, {}) == {"project_pk": REQUIRED}


def test_an_untyped_kwargs_provider_relaxes_no_read(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=[Refuse()],
        reads=PROJECT,
        kwargs=lambda: {"project_pk": 7},
    )
    assert _refused_at_the_shape_check(spec, ada, {}) == {"project_pk": REQUIRED}


def test_a_target_read_the_lookup_s_kwargs_provider_fills_is_not_demanded_of_the_caller(
    ada: Any,
) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    service = Record()
    target = nested(RETRIEVE, selector=note_by_pk, reads=PK, kwargs=_pk_provider(note.pk)[0])
    spec = ServiceSpec(service=service, permissions=OPEN, instance_selector_spec=target)
    dispatch(spec, principal=ada, arguments={})
    assert service.calls[0]["instance"] == note


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_target_read_the_lookup_s_provider_declines_is_refused_where_the_selector_asks(
    ada: Any, declined: Any
) -> None:
    provider, calls = _pk_provider(declined)
    service = Record()
    target = nested(RETRIEVE, selector=note_by_pk, reads=PK, kwargs=provider)
    spec = ServiceSpec(service=service, permissions=OPEN, instance_selector_spec=target)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.detail == {"pk": REQUIRED}
    assert calls == [None]
    assert service.calls == []


def test_a_selector_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller(
    ada: Any,
) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    spec = SelectorSpec(
        kind=RETRIEVE,
        selector=note_by_pk,
        permissions=OPEN,
        reads=PK,
        kwargs=_pk_provider(note.pk)[0],
    )
    assert dispatch(spec, principal=ada, arguments={}).value == note


def test_a_many_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller(
    ada: Any,
) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        many=True,
        validator=Titled(),
        reads=PROJECT,
        kwargs=_project_provider()[0],
    )
    dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
    assert service.calls[0]["project_pk"] == 7


# A key a typed provider fills is the server's for the whole call: the caller's
# value for it is checked and then dropped, so a provider that leaves it out or
# declines it with ``UNSET`` leaves it absent rather than the caller's.


class _MaybeTenant(TypedDict, total=False):
    tenant: str


TENANT = Parameters.of(Parameter("tenant", "string", required=True))


def test_a_server_owned_key_the_provider_leaves_out_is_never_the_caller_s(ada: Any) -> None:
    # A provider that fills the tenant for the users who have one, and this
    # user has none: ``total=False`` still reads as filled.
    def tenant_of(*, user: Any) -> _MaybeTenant:
        return {}

    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, reads=TENANT, kwargs=tenant_of)
    dispatch(spec, principal=ada, arguments={"tenant": "victim-corp"})
    assert "tenant" not in service.calls[0]


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_filled_read_the_caller_sends_is_refused_where_the_service_asks_if_the_provider_declines(
    ada: Any, declined: Any
) -> None:
    provider, calls = _project_provider(project_pk=declined)
    ran: list[int] = []

    def create(*, project_pk: int) -> None:
        ran.append(project_pk)

    spec = ServiceSpec(service=create, permissions=OPEN, reads=PROJECT, kwargs=provider)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"project_pk": 99})
    assert caught.value.detail == {"project_pk": REQUIRED}
    assert calls == [None]
    assert ran == []


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_filled_target_read_the_caller_sends_never_reaches_the_lookup(
    ada: Any, bob: Any, declined: Any
) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    provider, calls = _pk_provider(declined)
    service = Record()
    target = nested(RETRIEVE, selector=note_by_pk, reads=PK, kwargs=provider)
    spec = ServiceSpec(service=service, permissions=OPEN, instance_selector_spec=target)
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk})
    assert caught.value.detail == {"pk": REQUIRED}
    assert calls == [None]
    assert service.calls == []


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_selector_spec_s_filled_read_the_caller_sends_never_reaches_its_selector(
    ada: Any, bob: Any, declined: Any
) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    spec = SelectorSpec(
        kind=RETRIEVE,
        selector=note_by_pk,
        permissions=OPEN,
        reads=PK,
        kwargs=_pk_provider(declined)[0],
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk})
    assert caught.value.detail == {"pk": REQUIRED}


class _TitleForm(forms.Form):
    title = forms.CharField()


@pytest.mark.parametrize("declined", [UNSET, _OMITTED], ids=["unset", "omitted"])
def test_a_filled_field_the_caller_sends_is_refused_by_the_validator_if_the_provider_declines(
    ada: Any, declined: Any
) -> None:
    def server() -> _ServerTitle:
        return {} if declined is _OMITTED else {"title": declined}

    spec = ServiceSpec(
        service=Record(), permissions=OPEN, validator=FormValidator(_TitleForm), input_data=server
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"title": "caller's"})
    assert caught.value.detail == {"title": REQUIRED}


def test_a_filled_field_a_many_row_sends_is_refused_by_the_validator_if_the_provider_declines(
    ada: Any,
) -> None:
    provider, _ = _title_provider(title=UNSET)
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        many=True,
        validator=FormValidator(_TitleForm),
        input_data=provider,
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"items": [{"title": "caller's"}]})
    assert caught.value.detail == {"items": {0: {"title": REQUIRED}}}
    assert service.calls == []


def test_a_many_spec_s_filled_read_the_caller_sends_is_refused_where_the_service_asks(
    ada: Any,
) -> None:
    provider, calls = _project_provider(project_pk=_OMITTED)
    ran: list[int] = []

    def create(*, project_pk: int) -> None:
        ran.append(project_pk)

    spec = ServiceSpec(
        service=create,
        permissions=OPEN,
        many=True,
        validator=Titled(),
        reads=PROJECT,
        kwargs=provider,
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}], "project_pk": 99})
    assert caught.value.detail == {"project_pk": REQUIRED}
    assert calls == [None]
    assert ran == []


class _DecliningProject(TypedDict):
    project_pk: int | UnsetType


def _declining_project(calls: list[None]) -> Callable[[], _DecliningProject]:
    def server() -> _DecliningProject:
        calls.append(None)
        return {"project_pk": UNSET}

    return server


def test_a_declinable_key_stays_the_caller_s(ada: Any) -> None:
    # Not filled, so neither relaxed nor dropped: the caller's value is the
    # one the service receives when the provider declines.
    calls: list[None] = []
    service = Record()
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=PROJECT, kwargs=_declining_project(calls)
    )
    dispatch(spec, principal=ada, arguments={"project_pk": 3})
    assert service.calls[0]["project_pk"] == 3
    assert calls == [None]


def test_a_declinable_key_stays_required_of_the_caller(ada: Any) -> None:
    # Refused by the shape check, which answers before the class-level check
    # refuses this principal: relaxed, the call would reach that refusal.
    calls: list[None] = []
    spec = ServiceSpec(
        service=Record(), permissions=[Refuse()], reads=PROJECT, kwargs=_declining_project(calls)
    )
    assert _refused_at_the_shape_check(spec, ada, {}) == {"project_pk": REQUIRED}
    assert calls == []


# --- the scope check: a set, or nothing, asked where no row is resolved.


def _guarded(check: Scoped, **kwargs: Any) -> tuple[ServiceSpec, Record]:
    service = Record()
    return ServiceSpec(service=service, permissions=[check], **kwargs), service


def test_a_create_asks_the_scope_check_of_nothing(ada: Any) -> None:
    check = Scoped(refuse_scope=True)
    calls: list[None] = []
    spec, service = _guarded(check, validator=Bare(), input_data=lambda: calls.append(None) or {})
    with pytest.raises(NotPermitted) as caught:
        dispatch(spec, principal=ada, arguments={})
    assert caught.value.message == "Not within your scope."
    assert check.scopes == [None]
    # Before the providers, as djangorestframework-services guards before them.
    assert calls == []
    assert service.calls == []


def test_a_collection_target_asks_the_scope_check_of_its_set(ada: Any, bob: Any) -> None:
    mine = Note.objects.create(owner=ada, title="mine")
    Note.objects.create(owner=bob, title="theirs")
    check = Scoped(refuse_scope=True)
    spec, service = _guarded(check, collection_selector_spec=nested(LIST, selector=notes_of))
    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={})
    assert check.scopes == [[mine]]
    assert service.calls == []


def test_an_empty_collection_is_asked_too(ada: Any) -> None:
    check = Scoped()
    spec, service = _guarded(check, collection_selector_spec=nested(LIST, selector=notes_of))
    dispatch(spec, principal=ada, arguments={})
    assert check.scopes == [[]]
    assert len(service.calls) == 1


def test_a_missing_row_allow_none_lets_through_asks_the_scope_check_of_nothing(ada: Any) -> None:
    check = Scoped(refuse_scope=True)
    spec, service = _guarded(
        check,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK, allow_none=True),
    )
    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={"pk": 404})
    assert check.scopes == [None]


def test_a_found_row_is_object_checked_and_never_scope_checked(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    check = Scoped(refuse_scope=True)
    spec, service = _guarded(
        check, instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK)
    )
    dispatch(spec, principal=ada, arguments={"pk": note.pk})
    assert (check.rows, check.scopes) == ([note], [])
    assert service.calls[0]["instance"] == note


def test_a_missing_row_without_allow_none_asks_no_check(ada: Any) -> None:
    check = Scoped(refuse_scope=True)
    spec, _ = _guarded(
        check, instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK)
    )
    result = dispatch(spec, principal=ada, arguments={"pk": 404})
    assert result.kind == "not_found"
    assert (check.rows, check.scopes) == ([], [])


def test_a_grant_that_checked_the_target_skips_the_scope_check_only_for_a_target_handed_in(
    ada: Any,
) -> None:
    check = Scoped(refuse_scope=True)
    spec, service = _guarded(check)
    grant = Grant(spec, ada, target_checked=True)
    # Handed the target the grant was minted for, dispatch asks nothing twice.
    dispatch(spec, principal=ada, arguments={}, grant=grant, target=None)
    assert check.scopes == []
    assert len(service.calls) == 1
    # Without it, the grant says nothing about what dispatch resolves itself.
    with pytest.raises(NotPermitted):
        dispatch(spec, principal=ada, arguments={}, grant=grant)
    assert check.scopes == [None]
    assert len(service.calls) == 1


def test_a_grant_that_checked_another_row_does_not_cover_the_row_dispatch_finds(
    ada: Any, bob: Any
) -> None:
    theirs = Note.objects.create(owner=bob, title="theirs")
    check = OwnerOnly()
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=[check],
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
    )
    with pytest.raises(NotPermitted):
        dispatch(
            spec,
            principal=ada,
            arguments={"pk": theirs.pk},
            grant=Grant(spec, ada, target_checked=True),
        )
    assert check.rows == [theirs]
    assert service.calls == []


def test_a_list_selector_spec_asks_the_scope_check_of_its_rows(ada: Any) -> None:
    mine = Note.objects.create(owner=ada, title="mine")
    check = Scoped(refuse_scope=True)
    precondition = _Precondition()
    spec = SelectorSpec(
        kind=LIST, selector=notes_of, permissions=[check], preconditions=[precondition]
    )
    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={})
    assert check.scopes == [[mine]]
    # Before the preconditions, as the object-level check runs before a row's.
    assert precondition.calls == []


def test_a_retrieve_selector_spec_s_none_under_allow_none_is_asked_nothing(ada: Any) -> None:
    check = Scoped(refuse_scope=True)
    spec = retrieve(permissions=[check], allow_none=True)
    result = dispatch(spec, principal=ada, arguments={"pk": 404})
    assert (result.kind, result.value) == ("instance", None)
    assert (check.rows, check.scopes) == ([], [])


# --- allow_none on a LIST: a selector's None is the empty list.


def _nothing(**pool: Any) -> None:
    return None


def test_a_list_selector_s_none_under_allow_none_is_the_empty_list(ada: Any) -> None:
    check = Scoped()
    seen: list[Any] = []

    def precondition(*, collection: Any) -> None:
        seen.append(collection)

    spec = SelectorSpec(
        kind=LIST,
        selector=_nothing,
        permissions=[check],
        allow_none=True,
        presenter=Titles(),
        preconditions=[precondition],
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert result == DispatchResult(kind="list", value=[])
    # Asked of the empty set, as an empty queryset is, and never of ``None``.
    assert check.scopes == [[]]
    assert seen == [[]]
    assert present(spec, result) == []


def test_a_list_selector_s_none_under_allow_none_is_refused_as_an_empty_set(ada: Any) -> None:
    check = Scoped(refuse_scope=True)
    spec = SelectorSpec(kind=LIST, selector=_nothing, permissions=[check], allow_none=True)

    with pytest.raises(NotPermitted, match=r"^Not within your scope\.$"):
        dispatch(spec, principal=ada, arguments={})

    assert check.scopes == [[]]


def test_a_list_selector_s_none_under_allow_none_skips_the_shaping(ada: Any) -> None:
    # Nothing to shape: the shaping check's "returned None" refusal does not
    # answer for a None the spec says it may return.
    spec = SelectorSpec(
        kind=LIST, selector=_nothing, permissions=OPEN, allow_none=True, select_related=["owner"]
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert result == DispatchResult(kind="list", value=[])


def test_a_list_selector_s_rows_under_allow_none_are_its_rows(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="kept")
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN, allow_none=True)

    result = dispatch(spec, principal=ada, arguments={})

    assert list(result.value) == [note]


def test_a_retrieve_selector_s_own_none_under_allow_none_stays_none(ada: Any) -> None:
    # A RETRIEVE's ``None`` is a missing row, never an empty list.
    spec = retrieve(selector=_nothing, allow_none=True)

    result = dispatch(spec, principal=ada, arguments={"pk": 404})

    assert result == DispatchResult(kind="instance", value=None)


def test_a_list_selector_s_none_without_allow_none_is_left_as_it_was(ada: Any) -> None:
    # Unchanged: the scope check is asked of ``None``, the result carries it,
    # and presenting it as a list fails as the author's error.
    check = Scoped()
    spec = SelectorSpec(kind=LIST, selector=_nothing, permissions=[check])

    result = dispatch(spec, principal=ada, arguments={})

    assert result == DispatchResult(kind="list", value=None)
    assert check.scopes == [None]
    with pytest.raises(TypeError, match="'NoneType' object is not iterable"):
        present(spec, result)


def test_a_collection_selector_s_none_under_allow_none_is_an_empty_collection(ada: Any) -> None:
    check = Scoped()
    service = Record(returns="done")
    spec = ServiceSpec(
        service=service,
        permissions=[check],
        collection_selector_spec=nested(LIST, selector=_nothing, allow_none=True),
    )

    dispatch(spec, principal=ada, arguments={})

    assert check.scopes == [[]]
    assert service.calls[0]["collection"] == []


def test_a_list_output_selector_s_none_under_allow_none_is_the_empty_list(ada: Any) -> None:
    spec = ServiceSpec(
        service=Record(returns="done"),
        permissions=OPEN,
        output_selector_spec=nested(LIST, selector=_nothing, allow_none=True),
    )

    result = dispatch(spec, principal=ada, arguments={})

    assert (result.kind, result.value) == ("list", [])


# --- target=: a target the caller resolved, used as the resolved one.


class _Counting:
    """A RETRIEVE target selector that counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, pk: int) -> Any:
        self.calls += 1
        return Note.objects.filter(pk=pk)


def test_a_pre_resolved_target_runs_no_lookup_and_is_object_checked_once(
    ada: Any, bob: Any
) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    theirs = Note.objects.create(owner=bob, title="theirs")
    selector = _Counting()
    check = Scoped()
    spec, service = _guarded(
        check, instance_selector_spec=nested(RETRIEVE, selector=selector, reads=PK)
    )
    dispatch(spec, principal=ada, arguments={"pk": note.pk}, target=note)
    assert selector.calls == 0
    assert check.rows == [note]
    assert service.calls[0]["instance"] == note
    # Not a lookup skipped and a check with it: a row the principal may not
    # touch is still refused.
    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={"pk": theirs.pk}, target=theirs)


def test_a_pre_resolved_target_under_a_grant_that_checked_it_is_checked_never(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    check = Scoped()
    spec, service = _guarded(
        check, instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK)
    )
    grant = Grant(spec, ada, target_checked=True)
    dispatch(spec, principal=ada, arguments={"pk": note.pk}, target=note, grant=grant)
    assert check.rows == []
    assert service.calls[0]["instance"] == note


def test_a_pre_resolved_target_reaches_the_providers_and_the_validator(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="Row")
    seen: list[Any] = []

    def server(*, instance: Note) -> dict[str, Any]:
        seen.append(instance)
        return {}

    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        input_data=server,
    )
    dispatch(spec, principal=ada, arguments={"pk": note.pk, "title": "T"}, target=note)
    assert seen == [note]
    assert validator.calls[0][1].target == note


def test_a_pre_resolved_target_s_reads_are_still_checked_as_declared(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    spec, service = _guarded(
        Scoped(), instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK)
    )
    with pytest.raises(InvalidArguments) as caught:
        dispatch(spec, principal=ada, arguments={}, target=note)
    assert caught.value.detail == {"pk": REQUIRED}
    assert service.calls == []


def test_a_pre_resolved_none_is_not_found_unless_allow_none(ada: Any) -> None:
    check = Scoped()
    spec, service = _guarded(
        check, instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK)
    )
    assert dispatch(spec, principal=ada, arguments={"pk": 1}, target=None).kind == "not_found"
    assert service.calls == []


def test_a_pre_resolved_collection_is_the_collection_and_scope_checked(ada: Any) -> None:
    rows = [Note.objects.create(owner=ada, title="mine")]
    check = Scoped()
    spec, service = _guarded(check, collection_selector_spec=nested(LIST, selector=notes_of))
    dispatch(spec, principal=ada, arguments={}, target=rows)
    assert service.calls[0]["collection"] is rows
    assert check.scopes == [rows]


def test_a_create_takes_a_pre_resolved_none_and_refuses_a_row(ada: Any) -> None:
    check = Scoped()
    spec, service = _guarded(check)
    dispatch(spec, principal=ada, arguments={}, target=None)
    assert check.scopes == [None]
    assert "instance" not in service.calls[0]
    row = Note.objects.create(owner=ada, title="mine")
    with pytest.raises(TypeError, match="declares no target selector"):
        dispatch(spec, principal=ada, arguments={}, target=row)


def test_a_selector_spec_refuses_a_pre_resolved_target(ada: Any) -> None:
    spec = retrieve()
    with pytest.raises(TypeError, match="target= is a ServiceSpec's"):
        dispatch(spec, principal=ada, arguments={"pk": 1}, target=None)


class Rows(Titled):
    """``Titled``, refusing a row titled ``bad`` by field and one titled ``own`` as a row."""

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        values = super().validate(arguments, context)
        if values.get("title") == "bad":
            raise InvalidArguments({"title": ["Not this one."]})
        if values.get("title") == "own":
            raise InvalidArguments({"non_field_errors": ["Not this row."]})
        return values


class TestMany:
    """A ``many`` spec: a list of rows, each checked and validated, then one run.

    Every spec is built inside its test, so a tree without ``many`` fails each
    test on its own.
    """

    def test_the_service_runs_once_with_every_validated_row(self, ada: Any) -> None:
        service = Record(returns=["a", "b"])
        validator = Titled()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=validator)
        result = dispatch(
            spec, principal=ada, arguments={"items": [{"title": " a "}, {"title": "b"}]}
        )
        assert result.kind == "list"
        assert result.value == ["a", "b"]
        assert result.data == [{"title": "a"}, {"title": "b"}]
        [call] = service.calls
        assert call["data"] == [{"title": "a"}, {"title": "b"}]
        assert call["items"] == [{"title": "a"}, {"title": "b"}]
        assert "title" not in call
        # Each row is validated on its own, with no target in its context.
        assert [args for args, _ in validator.calls] == [{"title": " a "}, {"title": "b"}]
        assert {context.target for _, context in validator.calls} == {None}

    def test_an_empty_list_runs_the_service_on_no_rows(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=Titled())
        dispatch(spec, principal=ada, arguments={"items": []})
        assert service.calls[0]["data"] == []

    def test_a_shape_refusal_and_a_validator_refusal_are_one_tree_by_index(self, ada: Any) -> None:
        # Row 0 is well-shaped and refused by the Validator alone, row 2 by the
        # shape check alone, so each address is answered by the check it names.
        service = Record()
        validator = Rows()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=validator)
        rows = [{"title": "bad"}, {"title": "fine"}, {"title": 3}]
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": rows})
        assert refused.value.detail == {
            "items": {0: {"title": ["Not this one."]}, 2: {"title": [expected_type("string")]}}
        }
        assert refused.value.detail["items"][0]["title"] != [expected_type("string")]
        # Every row the shape check let through was validated, and none ran.
        assert [args for args, _ in validator.calls] == [{"title": "bad"}, {"title": "fine"}]
        assert service.calls == []

    def test_a_row_s_own_message_sits_under_non_field_errors_in_the_row(self, ada: Any) -> None:
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Rows())
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": ["not a row", {"title": "own"}]})
        assert refused.value.detail == {
            "items": {
                0: {"non_field_errors": [expected_type("object")]},
                1: {"non_field_errors": ["Not this row."]},
            }
        }

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"items": "nope"}, expected_type("array")),
            ({"items": None}, "This field cannot be null."),
            ({}, "This field is required."),
        ],
        ids=["not-a-list", "null", "absent"],
    )
    def test_the_list_s_own_refusal_is_a_list_under_its_name(
        self, ada: Any, arguments: dict[str, Any], message: str
    ) -> None:
        validator = Titled()
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=validator)
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments=arguments)
        assert refused.value.detail == {"items": [message]}
        assert validator.calls == []

    def test_the_list_travels_under_its_declared_name(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(
            service=service, permissions=OPEN, many=True, many_argument="rows", validator=Titled()
        )
        dispatch(spec, principal=ada, arguments={"rows": [{"title": "a"}]})
        assert service.calls[0]["rows"] == [{"title": "a"}]
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"rows": [{}]})
        assert refused.value.detail == {"rows": {0: {"title": ["This field is required."]}}}

    def test_a_read_beside_the_list_reaches_the_service_once_and_never_the_validator(
        self, ada: Any
    ) -> None:
        calls: list[bool] = []

        def bulk(*, data: list[Any], confirmed: bool = False) -> None:
            calls.append(confirmed)

        validator = Titled()
        spec = ServiceSpec(
            service=bulk,
            permissions=OPEN,
            many=True,
            validator=validator,
            reads=Parameters.of(Parameter("confirmed", "boolean")),
        )
        rows = [{"title": "a"}, {"title": "b"}]
        dispatch(spec, principal=ada, arguments={"items": rows, "confirmed": True})
        assert calls == [True]
        assert [args for args, _ in validator.calls] == rows

    def test_any_other_top_level_key_is_refused_as_unknown(self, ada: Any) -> None:
        validator = Titled()
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=validator)
        arguments = {"items": [{"title": "a"}], "title": "a"}
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments=arguments)
        assert refused.value.detail == {"title": ["Unknown argument."]}
        assert validator.calls == []

    def test_an_unknown_key_in_a_row_follows_the_call_s_policy(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=Titled())
        arguments = {"items": [{"title": "a", "colour": "red"}]}
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments=arguments)
        assert refused.value.detail == {"items": {0: {"colour": ["Unknown argument."]}}}
        dispatch(
            spec,
            principal=ada,
            arguments=arguments,
            unknown_arguments=UnknownArguments.IGNORE,
        )
        assert service.calls[0]["data"] == [{"title": "a"}]

    def test_every_row_is_written_in_one_transaction(self, ada: Any) -> None:
        def bulk(*, data: list[dict[str, Any]], user: Any) -> None:
            for row in data:
                Note.objects.create(owner=user, title=row["title"])
            raise RuntimeError("after every row was written")

        spec = ServiceSpec(service=bulk, permissions=OPEN, many=True, validator=Titled())
        with pytest.raises(RuntimeError):
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}, {"title": "b"}]})
        assert not Note.objects.exists()

    def test_the_scope_check_is_asked_of_nothing_before_any_row_is_validated(
        self, ada: Any
    ) -> None:
        # A list of rows resolves no target, so the scope check is asked about
        # ``None``, as for a create, and never about the caller's rows.
        validator = Titled()
        check = Scoped(refuse_scope=True)
        spec = ServiceSpec(service=Record(), permissions=[check], many=True, validator=validator)
        with pytest.raises(NotPermitted, match="Not within your scope."):
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
        assert check.scopes == [None]
        assert validator.calls == []

    def test_a_malformed_row_from_a_refused_principal_is_not_permitted(self, ada: Any) -> None:
        # A row is checked with its Validator, after authorization, so a
        # principal refused learns nothing about the rows it sent; the list's
        # own shape is checked before, as any argument's is.
        spec = ServiceSpec(service=Record(), permissions=[Refuse()], many=True, validator=Titled())
        with pytest.raises(NotPermitted, match="Only editors may run this."):
            dispatch(spec, principal=ada, arguments={"items": [{"title": 3}]})
        with pytest.raises(InvalidArguments):
            dispatch(spec, principal=ada, arguments={"items": "nope"})

    def test_partial_relaxes_every_row(self, ada: Any) -> None:
        class Lenient(Titled):
            def validate(
                self, arguments: Mapping[str, Any], context: ValidationContext
            ) -> dict[str, Any]:
                self.calls.append((dict(arguments), context))
                return dict(arguments)

        service = Record()
        validator = Lenient()
        spec = ServiceSpec(
            service=service, permissions=OPEN, many=True, partial=True, validator=validator
        )
        dispatch(spec, principal=ada, arguments={"items": [{}, {"title": "b"}]})
        assert service.calls[0]["data"] == [{}, {"title": "b"}]
        assert {context.partial for _, context in validator.calls} == {True}

    def test_partial_leaves_the_list_and_the_reads_required(self, ada: Any) -> None:
        spec = ServiceSpec(
            service=Record(),
            permissions=OPEN,
            many=True,
            partial=True,
            validator=Titled(),
            reads=Parameters.of(Parameter("title", "string", required=True)),
        )
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={})
        assert refused.value.detail == {
            "title": ["This field is required."],
            "items": ["This field is required."],
        }

    def test_input_data_fills_each_row(self, ada: Any) -> None:
        seen: list[dict[str, Any]] = []

        def fill(*, user: Any) -> _ServerTitle:
            seen.append({"user": user})
            return {"title": "from the server"}

        service = Record()
        validator = Titled()
        spec = ServiceSpec(
            service=service, permissions=OPEN, many=True, validator=validator, input_data=fill
        )
        dispatch(spec, principal=ada, arguments={"items": [{}, {"title": "mine"}]})
        # Called once for the call, and its values outrank each row's.
        assert seen == [{"user": ada}]
        assert [args for args, _ in validator.calls] == [
            {"title": "from the server"},
            {"title": "from the server"},
        ]

    def test_each_row_s_validator_sees_only_the_keys_it_declares(self, ada: Any) -> None:
        # The shape check refuses an unknown key inside a row, so only a
        # provider can put one there; a serializer ignores a key it has no
        # field for, and so is the Validator never handed one.
        validator = Titled()
        spec = ServiceSpec(
            service=Record(),
            permissions=OPEN,
            many=True,
            validator=validator,
            input_data=lambda: {"undeclared": 1},
        )
        dispatch(spec, principal=ada, arguments={"items": [{"title": "mine"}]})
        assert [args for args, _ in validator.calls] == [{"title": "mine"}]

    def test_a_value_a_row_binds_is_refused(self, ada: Any) -> None:
        class Binding(Titled):
            def validated(
                self, arguments: Mapping[str, Any], context: ValidationContext
            ) -> Validated:
                return Validated(values=dict(arguments), data=dict(arguments), pool={"form": 1})

        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Binding())
        with pytest.raises(ImproperlyConfigured) as refused:
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
        assert str(refused.value).startswith(
            "The Validator bound the key(s) ['form'] for row 0 of a many call."
        )

    def test_a_service_parameter_named_after_a_row_field_is_the_author_s_error(
        self, ada: Any
    ) -> None:
        # A row's fields are never spread, so nothing a caller sends fills
        # ``title``: the service's own error, never a missing argument.
        def bulk(*, title: str) -> None: ...

        spec = ServiceSpec(service=bulk, permissions=OPEN, many=True, validator=Titled())
        with pytest.raises(TypeError, match="title"):
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})

    @pytest.mark.parametrize("target", [None, "a row"])
    def test_a_pre_resolved_target_is_refused(self, ada: Any, target: Any) -> None:
        check = Scoped()
        spec = ServiceSpec(service=Record(), permissions=[check], many=True, validator=Titled())
        with pytest.raises(TypeError) as refused:
            dispatch(spec, principal=ada, arguments={"items": []}, target=target)
        assert str(refused.value).startswith(
            "target= stands in for a target selector's lookup, and a many spec resolves no target:"
        )
        assert check.scopes == []

    def test_arguments_that_are_no_mapping_are_refused_by_the_shape_check(self, ada: Any) -> None:
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Titled())
        arguments: Any = [{"title": "a"}]
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments=arguments)
        assert refused.value.detail == {"non_field_errors": [expected_type("object")]}

    def test_a_tuple_of_rows_is_a_list(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=Titled())
        dispatch(spec, principal=ada, arguments={"items": ({"title": "a"},)})
        assert service.calls[0]["data"] == [{"title": "a"}]

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [(SelectorKind.LIST, "list"), (SelectorKind.RETRIEVE, "instance")],
    )
    def test_an_output_selector_s_kind_decides_what_its_re_read_is(
        self, ada: Any, kind: SelectorKind, expected: str
    ) -> None:
        output = SelectorSpec(kind=kind, selector=lambda *, result: result)
        spec = ServiceSpec(
            service=Record(returns=[]),
            permissions=OPEN,
            many=True,
            validator=Titled(),
            output_selector_spec=output,
        )
        result = dispatch(spec, principal=ada, arguments={"items": []})
        assert result.kind == expected

    def test_its_affordances_and_preconditions_are_answered_once(self, ada: Any) -> None:
        asked: list[str] = []
        seen: list[Any] = []

        def books_open() -> bool:
            asked.append("affordance")
            return True

        def checked(*, data: list[Any]) -> None:
            seen.append(data)

        spec = ServiceSpec(
            service=Record(),
            permissions=OPEN,
            many=True,
            validator=Titled(),
            affordances=[Affordance(code="books_open", reason="Closed.", when=books_open)],
            preconditions=[checked],
        )
        dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}, {"title": "b"}]})
        assert asked == ["affordance"]
        assert seen == [[{"title": "a"}, {"title": "b"}]]

    def test_a_many_service_returning_none_presents_none(self, ada: Any) -> None:
        # The write has committed by the time the result is presented, so a
        # bulk service with nothing to return must not be refused there.
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Titled())
        result = dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
        assert result.kind == "instance"
        assert present(spec, result) is None

    def test_a_list_of_rows_past_the_default_maximum_is_refused_at_the_list(self, ada: Any) -> None:
        # Refused before any row is checked or validated: one transaction over
        # every row and one Validator run each is the cost being bounded.
        service = Record()
        validator = Titled()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=validator)
        rows = [{"title": 3}] * 1001
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": rows})
        assert refused.value.detail == {
            "items": ["Ensure this field has no more than 1000 elements."]
        }
        assert validator.calls == []
        assert service.calls == []

    @override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=2)
    def test_a_list_past_its_maximum_is_refused_beside_the_top_level_s_own_refusals(
        self, ada: Any
    ) -> None:
        spec = ServiceSpec(
            service=Record(),
            permissions=OPEN,
            many=True,
            validator=Titled(),
            reads=Parameters.of(Parameter("confirm", "boolean", required=True)),
        )
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}] * 3})
        assert refused.value.detail == {
            "confirm": ["This field is required."],
            "items": ["Ensure this field has no more than 2 elements."],
        }

    @override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=2)
    def test_a_list_at_its_maximum_runs(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(service=service, permissions=OPEN, many=True, validator=Titled())
        dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}, {"title": "b"}]})
        assert service.calls[0]["data"] == [{"title": "a"}, {"title": "b"}]

    def test_many_min_length_is_the_rule_an_empty_list_is_refused_by(self, ada: Any) -> None:
        service = Record()
        spec = ServiceSpec(
            service=service, permissions=OPEN, many=True, validator=Titled(), many_min_length=1
        )
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": []})
        assert coded(refused.value.detail) == {
            "items": [("Ensure this field has at least 1 elements.", "min_length")]
        }
        assert service.calls == []
        # A list that meets it is checked as any other: the empty stand-in the
        # top level is checked with is never held to the minimum.
        dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}]})
        assert service.calls[0]["data"] == [{"title": "a"}]

    def test_many_max_length_outranks_the_default(self, ada: Any) -> None:
        spec = ServiceSpec(
            service=Record(), permissions=OPEN, many=True, validator=Titled(), many_max_length=2
        )
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": [{"title": "a"}] * 3})
        assert refused.value.detail == {"items": ["Ensure this field has no more than 2 elements."]}


def test_a_json_list_past_the_default_maximum_is_refused_at_its_parameter(ada: Any) -> None:
    service = Record()
    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        reads=Parameters.of(Parameter("ids", "array", items="integer")),
    )
    with pytest.raises(InvalidArguments) as refused:
        dispatch(spec, principal=ada, arguments={"ids": list(range(1001))})
    assert refused.value.detail == {"ids": ["Ensure this field has no more than 1000 elements."]}
    assert service.calls == []


class _Coded(str):
    """A message carrying a code the way a library's own does: DRF's ``ErrorDetail``, for one."""

    code = "blank"


class Blank(Titled):
    """``Titled``, refusing an empty title with a message that carries its own code."""

    message = _Coded("This field may not be blank.")

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        values = super().validate(arguments, context)
        if not values["title"]:
            raise InvalidArguments({"title": [self.message]})
        return values


class TestRefusalCodes:
    """Each refusal of a ``many`` call carries its code, whichever check answered it."""

    def test_a_row_s_shape_refusal_carries_its_code(self, ada: Any) -> None:
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Titled())
        rows = [{"title": "fine"}, {}, {"title": 3}]
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": rows})
        assert coded(refused.value.detail) == {
            "items": {
                1: {"title": [("This field is required.", "required")]},
                2: {"title": [("Expected a string.", "invalid")]},
            }
        }

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            ({}, ("This field is required.", "required")),
            ({"items": None}, ("This field cannot be null.", "null")),
            ({"items": "fine"}, ("Expected an array.", "not_a_list")),
        ],
    )
    def test_the_list_s_own_refusal_carries_its_code(
        self, ada: Any, arguments: dict[str, Any], expected: tuple[str, str]
    ) -> None:
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Titled())
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments=arguments)
        assert coded(refused.value.detail) == {"items": [expected]}

    def test_a_validator_s_own_messages_reach_the_tree_as_it_raised_them(self, ada: Any) -> None:
        # Not rewrapped: a coded message is the same object, and a plain one stays plain.
        validator = Blank()
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=validator)
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": [{"title": " "}]})
        assert refused.value.detail["items"][0]["title"][0] is validator.message
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=Rows())
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": [{"title": "bad"}]})
        assert type(refused.value.detail["items"][0]["title"][0]) is str
        # And on one call, where the Validator's tree is the refusal itself.
        validator = Blank()
        one = ServiceSpec(service=Record(), permissions=OPEN, validator=validator)
        with pytest.raises(InvalidArguments) as refused:
            dispatch(one, principal=ada, arguments={"title": " "})
        assert refused.value.detail["title"][0] is validator.message

    def test_a_row_the_shape_check_refuses_is_never_validated_as_on_one_call(
        self, ada: Any
    ) -> None:
        # Row 0's title is blank and it carries an unknown key: the shape check
        # answers it and the Validator never sees it, as a single call with the
        # same arguments is refused before its Validator runs. Row 1 is
        # well-shaped, so its blank title is the Validator's to refuse.
        validator = Blank()
        spec = ServiceSpec(service=Record(), permissions=OPEN, many=True, validator=validator)
        rows = [{"title": " ", "colour": "red"}, {"title": " "}]
        with pytest.raises(InvalidArguments) as refused:
            dispatch(spec, principal=ada, arguments={"items": rows})
        assert coded(refused.value.detail) == {
            "items": {
                0: {"colour": [("Unknown argument.", "unknown")]},
                1: {"title": [("This field may not be blank.", "blank")]},
            }
        }
        assert [arguments for arguments, _ in validator.calls] == [{"title": " "}]
        one = ServiceSpec(service=Record(), permissions=OPEN, validator=Blank())
        with pytest.raises(InvalidArguments) as refused:
            dispatch(one, principal=ada, arguments=rows[0])
        assert coded(refused.value.detail) == {"colour": [("Unknown argument.", "unknown")]}


def test_passthrough_is_refused_rather_than_run_as_ignore(ada: Any) -> None:
    # Sized so the policy is what answers: an active principal, an open spec
    # and an undeclared key the IGNORE branch would drop and run.
    spec = SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN)
    with pytest.raises(ValueError, match=r"UnknownArguments\.PASSTHROUGH is refused"):
        dispatch(
            spec,
            principal=ada,
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


# --- a declaration of another library's ----------------------------------------------------


def test_a_foreign_selector_declaration_runs_as_its_compiled_spec(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    source = Foreign(SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN))

    result = dispatch(source, principal=ada, arguments={})

    assert [row.pk for row in result.value] == [note.pk]
    assert source.compiles == [1]


def test_a_foreign_service_declaration_runs_as_its_compiled_spec(ada: Any) -> None:
    record = Record(returns="done")
    source = Foreign(ServiceSpec(service=record, permissions=OPEN, validator=Titled()))

    result = dispatch(source, principal=ada, arguments={"title": "T"})

    assert result.value == "done"
    assert record.calls[0]["title"] == "T"


def test_a_foreign_declaration_s_grant_is_its_compiled_spec_s(ada: Any) -> None:
    # A grant bound to the compiled spec covers the object it was compiled
    # from, so the class-level check is not asked twice.
    asked: list[Any] = []

    class Counted(PermissionCheck):
        def has_permission(self, principal: Any, spec: Any) -> bool:
            asked.append(spec)
            return True

    compiled = SelectorSpec(kind=LIST, selector=notes_of, permissions=[Counted()])
    source = Foreign(compiled)

    dispatch(source, principal=ada, arguments={}, grant=Grant(compiled, ada))

    assert asked == []


class _Counted(PermissionCheck):
    """Admits everyone, and records the spec each check is asked about."""

    def __init__(self) -> None:
        self.asked: list[Any] = []
        self.rows: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.asked.append(spec)
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.rows.append(target)
        return True


def test_a_grant_built_from_a_source_covers_the_source_and_its_compiled_spec(ada: Any) -> None:
    # The shape of an HTTP transport over another library's declarations: its
    # view authorizes the object it holds, mints the grant from that object,
    # and dispatches either the object or what it compiles to.
    check = _Counted()
    source = Foreign(SelectorSpec(kind=LIST, selector=notes_of, permissions=[check]))
    grant = Grant(source, ada)

    dispatch(source, principal=ada, arguments={}, grant=grant)
    dispatch(kernel_spec(source), principal=ada, arguments={}, grant=grant)

    assert check.asked == []


def test_a_grant_built_from_another_source_is_refused(ada: Any) -> None:
    source = Foreign(SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN))
    other = Foreign(SelectorSpec(kind=LIST, selector=notes_of, permissions=OPEN))

    with pytest.raises(NotPermitted, match="does not cover"):
        dispatch(source, principal=ada, arguments={}, grant=Grant(other, ada))


def test_a_source_s_grant_that_checked_the_target_covers_the_target_handed_in(ada: Any) -> None:
    note = Note.objects.create(owner=ada, title="mine")
    check = _Counted()
    record = Record()
    source = Foreign(
        ServiceSpec(
            service=record,
            permissions=[check],
            instance_selector_spec=nested(RETRIEVE, selector=note_by_pk, reads=PK),
        )
    )
    grant = Grant(source, ada, target_checked=True)

    dispatch(source, principal=ada, arguments={"pk": note.pk}, target=note, grant=grant)

    assert check.asked == []
    assert check.rows == []
    assert record.calls[0]["instance"] == note


def test_a_check_is_asked_about_the_compiled_spec_on_either_route(ada: Any) -> None:
    check = _Counted()
    source = Foreign(SelectorSpec(kind=LIST, selector=notes_of, permissions=[check]))

    authorize(source, ada)
    dispatch(source, principal=ada, arguments={})

    assert len(check.asked) == 2
    assert all(asked is kernel_spec(source) for asked in check.asked)
