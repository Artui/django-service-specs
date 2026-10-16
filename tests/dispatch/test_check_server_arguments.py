from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from typing_extensions import TypedDict

from django_service_specs.dispatch.check_server_arguments import check_server_arguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unset import UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, TENANT_SEEDS
from tests.dispatch_app.models import Note

pytestmark = pytest.mark.django_db

Check = Callable[..., None]

# The wording of each refusal, in the order the checks run, so a test asserts
# which one answered and that none before it did.
UNDECLARED = "which the spec does not declare"
BOTH = "both bound and withheld"
SEED = "a registered pool seed occupies"
PROVIDER = "a provider is annotated to fill or may fill"
UNFILLABLE = "which no call could then do without"
BAD_VALUE = "a value its parameter refuses"
ALL = (UNDECLARED, BOTH, SEED, PROVIDER, UNFILLABLE, BAD_VALUE)


def notes_in(**kwargs: Any) -> QuerySet[Note]:
    return Note.objects.none()


# Every combination the withheld check reads: required or not, a default or
# not, so each conjunct has a parameter that only it decides.
READS = Parameters.of(
    Parameter("project_pk", "integer", required=True),
    Parameter("draw_request_pk", "integer"),
    Parameter("status", "string", default="open"),
    Parameter("account_pk", "integer", required=True, default=3),
)


def scoped(reads: Parameters = READS, **kwargs: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_in, reads=reads, permissions=OPEN, **kwargs
    )


class _Tenant(TypedDict):
    tenant_pk: int


def fill_tenant() -> _Tenant:
    return {"tenant_pk": 1}


class _MaybeTenant(TypedDict):
    tenant_pk: int | UnsetType


def maybe_tenant() -> _MaybeTenant:
    return {"tenant_pk": 1}


class Declaring(Validator):
    """A Validator that declares the parameters it is given and validates nothing."""

    def __init__(self, *parameters: Parameter) -> None:
        self._parameters = Parameters.of(*parameters)

    def parameters(self) -> Parameters:
        return self._parameters

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def service(**kwargs: Any) -> None: ...


@pytest.fixture
def check(django_assert_num_queries: Any) -> Check:
    """``check_server_arguments``, run where a query would fail the test."""

    def run(spec: Any, server: ServerArguments, **kwargs: Any) -> None:
        with django_assert_num_queries(0):
            check_server_arguments(spec, server, **kwargs)

    return run


def refusal(check: Check, spec: Any, server: ServerArguments, **kwargs: Any) -> str:
    with pytest.raises(ImproperlyConfigured) as raised:
        check(spec, server, **kwargs)
    return str(raised.value)


def only(message: str, wording: str) -> None:
    """``message`` is the refusal ``wording`` names, and no other check's."""
    assert wording in message
    assert [other for other in ALL if other != wording and other in message] == []


def test_a_binding_that_means_what_it_says_passes(check: Check) -> None:
    check(
        scoped(),
        ServerArguments(values={"project_pk": 7}, withheld=frozenset({"draw_request_pk"})),
    )


def test_a_declaration_with_as_kernel_spec_is_read_as_its_compiled_spec(check: Check) -> None:
    class Source:
        def as_kernel_spec(self) -> SelectorSpec:
            return scoped()

    check(Source(), ServerArguments(values={"project_pk": 7}))
    message = refusal(check, Source(), ServerArguments(values={"nowhere": 1}))
    only(message, UNDECLARED)


class TestUndeclared:
    def test_every_undeclared_name_is_refused_in_order(self, check: Check) -> None:
        server = ServerArguments(values={"zeta": 1, "project_pk": 7}, withheld=frozenset({"alpha"}))
        message = refusal(check, scoped(), server)
        only(message, UNDECLARED)
        assert "alpha, zeta" in message
        assert "project_pk" not in message

    def test_a_field_inside_a_many_row_is_not_a_top_level_parameter(self, check: Check) -> None:
        # A ``many`` spec's rows travel inside one list, so a row's field has
        # no single value to bind; the read beside the list does.
        spec = ServiceSpec(
            service=service,
            validator=Declaring(Parameter("title", "string")),
            reads=Parameters.of(Parameter("project_pk", "integer")),
            many=True,
            permissions=OPEN,
        )
        check(spec, ServerArguments(values={"project_pk": 7}))
        message = refusal(check, spec, ServerArguments(values={"title": "Fixed"}))
        only(message, UNDECLARED)
        assert "title" in message


class TestBoth:
    def test_a_name_both_bound_and_withheld_is_refused(self, check: Check) -> None:
        # Each name declared, no seed and no provider, so only this check can answer.
        server = ServerArguments(
            values={"status": "open", "draw_request_pk": 1, "project_pk": 7},
            withheld=frozenset({"status", "draw_request_pk"}),
        )
        message = refusal(check, scoped(), server)
        only(message, BOTH)
        assert "draw_request_pk, status" in message
        assert "project_pk" not in message


class TestSeed:
    def test_a_parameter_a_registered_seed_occupies_is_refused(self, check: Check) -> None:
        # Declared, so the undeclared check passes it; a dispatcher seed such
        # as ``user`` can never be declared, so only a registered one reaches here.
        spec = scoped(reads=READS + Parameters.of(Parameter("tenant", "string")))
        message = refusal(
            check, spec, ServerArguments(values={"tenant": "acme"}), pool_seeds=TENANT_SEEDS
        )
        only(message, SEED)
        assert "tenant" in message

    def test_a_withheld_name_a_seed_occupies_is_refused_too(self, check: Check) -> None:
        spec = scoped(reads=READS + Parameters.of(Parameter("tenant", "string")))
        server = ServerArguments(withheld=frozenset({"tenant"}))
        only(refusal(check, spec, server, pool_seeds=TENANT_SEEDS), SEED)

    def test_the_pool_seeds_given_are_the_ones_read(self, check: Check) -> None:
        spec = scoped(reads=READS + Parameters.of(Parameter("tenant", "string")))
        check(spec, ServerArguments(values={"tenant": "acme"}))
        check(spec, ServerArguments(values={"tenant": "acme"}), pool_seeds=PoolSeeds())


class TestProvider:
    def test_a_name_a_typed_provider_fills_is_refused(self, check: Check) -> None:
        # Declared and no seed: the provider's answer would replace the bound
        # value inside dispatch, so the binding would do nothing.
        spec = scoped(
            reads=READS + Parameters.of(Parameter("tenant_pk", "integer")), kwargs=fill_tenant
        )
        message = refusal(check, spec, ServerArguments(values={"tenant_pk": 2}))
        only(message, PROVIDER)
        assert "tenant_pk" in message

    def test_a_name_a_provider_may_decline_is_refused_too(self, check: Check) -> None:
        # Left to the caller by ``server_owned_keys``, since the provider may
        # return ``UNSET``; on every call where it does not, its answer would
        # replace the bound value, so the binding cannot be relied on either.
        spec = scoped(
            reads=READS + Parameters.of(Parameter("tenant_pk", "integer")), kwargs=maybe_tenant
        )
        message = refusal(check, spec, ServerArguments(values={"tenant_pk": 2}))
        only(message, PROVIDER)
        assert "tenant_pk" in message

    def test_a_validator_field_input_data_fills_is_refused(self, check: Check) -> None:
        spec = ServiceSpec(
            service=service,
            validator=Declaring(Parameter("tenant_pk", "integer"), Parameter("title", "string")),
            input_data=fill_tenant,
            permissions=OPEN,
        )
        check(spec, ServerArguments(values={"title": "Fixed"}))
        message = refusal(check, spec, ServerArguments(withheld=frozenset({"tenant_pk"})))
        only(message, PROVIDER)

    def test_a_read_the_target_selector_s_provider_fills_is_refused(self, check: Check) -> None:
        target = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=notes_in,
            reads=Parameters.of(Parameter("tenant_pk", "integer")),
            kwargs=maybe_tenant,
        )
        spec = ServiceSpec(service=service, instance_selector_spec=target, permissions=OPEN)
        only(refusal(check, spec, ServerArguments(values={"tenant_pk": 2})), PROVIDER)

    def test_a_provider_whose_return_names_no_keys_refuses_no_name(self, check: Check) -> None:
        # Such a provider may fill any name and so, as for
        # ``server_owned_keys``, names none: nothing here is known statically.
        def untyped(**_: object) -> dict[str, object]:
            return {}

        spec = scoped(
            reads=READS + Parameters.of(Parameter("tenant_pk", "integer")), kwargs=untyped
        )
        check(spec, ServerArguments(values={"tenant_pk": 2}))


def picky(
    *,
    project_pk: int,
    draw_request_pk: int,
    region: str = "eu",
    search: str = "",
    account_pk: int = 3,
    tier: str,
) -> QuerySet[Note]:
    return Note.objects.none()


# Each read decided by one conjunct of the withheld check: whether the shape
# check demands it (required, with no declared default), and whether the
# selector that receives it declares it with no default of its own.
PICKY_READS = Parameters.of(
    Parameter("draw_request_pk", "integer"),
    Parameter("region", "string", required=True),
    Parameter("search", "string"),
    Parameter("account_pk", "integer", required=True, default=3),
    Parameter("tier", "string", required=True, default="free"),
    Parameter("note", "string"),
)


def picky_spec() -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=picky, reads=PICKY_READS, permissions=OPEN)


class Partial(Declaring):
    supports_partial = True


def write(*, title: str = "", body: str = "", pk: int = 0) -> None: ...


class TestWithheld:
    def test_a_required_name_with_no_default_cannot_be_withheld(self, check: Check) -> None:
        message = refusal(check, scoped(), ServerArguments(withheld=frozenset({"project_pk"})))
        only(message, UNFILLABLE)
        assert "project_pk" in message

    def test_a_demanded_read_is_refused_though_its_selector_has_a_default(
        self, check: Check
    ) -> None:
        # The shape check refuses it absent before the selector is asked, so
        # the selector's own default never answers: fails without the
        # "demanded" half of the read's disjunction.
        message = refusal(check, picky_spec(), ServerArguments(withheld=frozenset({"region"})))
        only(message, UNFILLABLE)
        assert "region" in message

    def test_a_read_its_selector_declares_with_no_default_cannot_be_withheld(
        self, check: Check
    ) -> None:
        # Optional to the shape check, so only the selector's signature can
        # say every call would be refused as missing: fails without the
        # callable's-default conjunct.
        message = refusal(
            check, picky_spec(), ServerArguments(withheld=frozenset({"draw_request_pk"}))
        )
        only(message, UNFILLABLE)
        assert "draw_request_pk" in message

    def test_a_declared_default_does_not_stand_in_for_the_selector_s(self, check: Check) -> None:
        # Required with a declared default, which the shape check accepts
        # absent and dispatch never applies, so the selector is called without
        # it and refuses.
        message = refusal(check, picky_spec(), ServerArguments(withheld=frozenset({"tier"})))
        only(message, UNFILLABLE)
        assert "tier" in message

    def test_an_optional_read_its_selector_defaults_may_be_withheld(self, check: Check) -> None:
        # Fails without the ``required`` conjunct.
        check(picky_spec(), ServerArguments(withheld=frozenset({"search"})))

    def test_a_provider_that_also_declares_a_read_is_not_judged(self, check: Check) -> None:
        # A stated limit: only the callable a read is handed to is read for a
        # default, so a provider declaring ``search`` with none is not.
        def scope(*, search: str) -> dict[str, object]:
            return {}

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=picky,
            reads=PICKY_READS,
            kwargs=scope,
            permissions=OPEN,
        )
        check(spec, ServerArguments(withheld=frozenset({"search"})))

    def test_a_required_read_with_both_defaults_may_be_withheld(self, check: Check) -> None:
        # Fails without the declared-default conjunct.
        check(picky_spec(), ServerArguments(withheld=frozenset({"account_pk"})))

    def test_a_read_its_selector_does_not_declare_may_be_withheld(self, check: Check) -> None:
        # Nothing asks for it, so nothing misses it: fails if the signature is
        # read for a name it does not have.
        check(picky_spec(), ServerArguments(withheld=frozenset({"note"})))

    def test_an_optional_name_with_no_default_may_be_withheld(self, check: Check) -> None:
        # The selector takes ``**kwargs``, so only the shape check could
        # demand it, and it does not.
        check(scoped(), ServerArguments(withheld=frozenset({"draw_request_pk"})))

    def test_a_required_name_with_no_default_may_be_bound(self, check: Check) -> None:
        # Fails without the ``withheld`` conjunct: a bound value fills it.
        check(scoped(), ServerArguments(values={"project_pk": 7}))

    def test_a_service_spec_s_read_is_judged_by_its_service(self, check: Check) -> None:
        def strict(*, pk: int) -> None: ...

        spec = ServiceSpec(
            service=strict, reads=Parameters.of(Parameter("pk", "integer")), permissions=OPEN
        )
        only(refusal(check, spec, ServerArguments(withheld=frozenset({"pk"}))), UNFILLABLE)
        lenient = ServiceSpec(
            service=write, reads=Parameters.of(Parameter("pk", "integer")), permissions=OPEN
        )
        check(lenient, ServerArguments(withheld=frozenset({"pk"})))

    def test_a_target_read_is_judged_by_the_target_s_selector(self, check: Check) -> None:
        def row(*, pk: int) -> QuerySet[Note]:
            return Note.objects.none()

        target = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=row,
            reads=Parameters.of(Parameter("pk", "integer")),
        )
        spec = ServiceSpec(service=write, instance_selector_spec=target, permissions=OPEN)
        only(refusal(check, spec, ServerArguments(withheld=frozenset({"pk"}))), UNFILLABLE)

    def test_a_validator_field_is_judged_by_the_shape_check_alone(self, check: Check) -> None:
        spec = ServiceSpec(
            service=write,
            validator=Declaring(
                Parameter("title", "string", required=True), Parameter("body", "string")
            ),
            permissions=OPEN,
        )
        only(refusal(check, spec, ServerArguments(withheld=frozenset({"title"}))), UNFILLABLE)
        check(spec, ServerArguments(withheld=frozenset({"body"})))

    def test_a_required_validator_field_may_be_withheld_from_a_partial_spec(
        self, check: Check
    ) -> None:
        # A partial call may leave out any Validator parameter, so dispatch
        # demands none of them: fails if the check reads the declaration
        # unrelaxed.
        spec = ServiceSpec(
            service=write,
            validator=Partial(Parameter("title", "string", required=True)),
            partial=True,
            permissions=OPEN,
        )
        check(spec, ServerArguments(withheld=frozenset({"title"})))


class TestBoundValues:
    def test_a_bound_value_its_parameter_refuses_fails_at_construction(self, check: Check) -> None:
        server = ServerArguments(values={"project_pk": "seven", "status": "closed"})
        message = refusal(check, scoped(), server)
        only(message, BAD_VALUE)
        assert "project_pk" in message
        assert "status" not in message

    @pytest.mark.parametrize(
        ("fmt", "natural", "wire"),
        [
            (
                "uuid",
                uuid.UUID("0b8a3c1e-5d2f-4e6a-9b7c-1d2e3f4a5b6c"),
                "0b8a3c1e-5d2f-4e6a-9b7c-1d2e3f4a5b6c",
            ),
            ("date", datetime.date(2024, 1, 31), "2024-01-31"),
            ("decimal", Decimal("1.5"), "1.5"),
        ],
    )
    def test_a_bound_value_takes_the_wire_spelling(
        self, check: Check, fmt: str, natural: Any, wire: str
    ) -> None:
        # The Python value a server holds is not the string the declaration
        # takes; refused where the transport is built, not on every call.
        spec = scoped(reads=Parameters.of(Parameter("pinned", "string", format=fmt)))
        message = refusal(check, spec, ServerArguments(values={"pinned": natural}))
        only(message, BAD_VALUE)
        check(spec, ServerArguments(values={"pinned": wire}))


def test_each_refusal_names_the_callable_whose_spec_it_is(check: Check) -> None:
    # A transport over many tools learns which one is misconfigured.
    assert "SelectorSpec for notes_in" in refusal(
        check, scoped(), ServerArguments(values={"nowhere": 1})
    )
    spec = ServiceSpec(
        service=write, validator=Declaring(Parameter("title", "string")), permissions=OPEN
    )
    assert "ServiceSpec for write" in refusal(check, spec, ServerArguments(values={"title": 1}))
