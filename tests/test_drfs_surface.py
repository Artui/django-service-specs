"""The names djangorestframework-services takes from this package, pinned.

djangorestframework-services depends on this package with an unbounded floor,
and re-exports or wraps the names below. A release here that renames one,
moves it to another module, or changes how it is called would not fail here:
it would fail every install of that package that resolves onto the release.
So each name is pinned in a table, and changing a row is a decision a pull
request here has to make in the open.

A row pins the shape a caller depends on, never the annotations, which a
release may widen without breaking anyone:

- **where it is importable**: the package root, its subpackage, and its leaf
  module, all the same object;
- **how it is called**: parameter names, their kinds (positional-only,
  positional, keyword-only, ``*args``, ``**kwargs``) and whether each has a
  default, written as a signature with the annotations and default values
  left out, so ``"spec, *, grant="`` is ``(spec, *, grant=None)``. A new
  optional keyword changes the row on purpose: it is the same one-line
  decision, and a reorder of positional parameters must fail;
- **what it is**: the methods and properties a caller or a subclass reads,
  the abstract methods a subclass must provide, its public base classes, an
  enum's members and a constant's value.

A row marked ``leaf_only`` pins a name importable from its leaf module and
from nowhere else, because exporting it would put it in the root's namespace
for no reader: a type variable a downstream generic subclass parameterizes
with, read as ``from <leaf> import ModelT``. Its row says what it is bound to
and whose type parameter it is.

A few rows are read directly by transports that reach this package without
going through djangorestframework-services, and are pinned for the same
reason. The test is pure Python and Django: it imports neither DRF nor
djangorestframework-services, as nothing in this suite may.
"""

from __future__ import annotations

import enum
import importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db.models import Model

import django_service_specs
from django_service_specs import (
    Parameters,
    SelectorKind,
    SelectorSpec,
    SpecRegistry,
    UnknownArguments,
    Unrestricted,
    adispatch,
    check_arguments,
    check_call,
    dispatch,
    parameters_schema,
)

_PACKAGE = "django_service_specs"
_UNPINNED = object()


@dataclass(frozen=True)
class Pin:
    """What one name promises its importers. Every facet left out is not pinned."""

    leaf: str
    signature: str | None = None
    methods: Mapping[str, str] = field(default_factory=dict)
    abstract: frozenset[str] | None = None
    bases: tuple[str | type, ...] = ()
    members: Mapping[str, object] | None = None
    value: object = _UNPINNED
    instance_of: str | None = None
    leaf_only: bool = False
    bound: type | None = None
    parameter_of: str | None = None


def _fn(leaf: str, signature: str) -> Pin:
    return Pin(leaf, signature=signature)


def _error(leaf: str, signature: str, base: str | type) -> Pin:
    return Pin(leaf, signature=signature, bases=(base,))


def _enum(leaf: str, members: Mapping[str, object], mixin: type) -> Pin:
    return Pin(leaf, members=members, bases=(mixin,))


def _protocol(leaf: str, call: str) -> Pin:
    # A Protocol class's own signature is typing's placeholder and differs
    # between Python versions; what an implementer must match is ``__call__``.
    return Pin(leaf, methods={"__call__": call})


# Grouped by subpackage. Adding a name is one row.
SURFACE: dict[str, Pin] = {
    # --- affordances --------------------------------------------------------------------------
    "enforce_affordances": _fn(
        "affordances.enforce_affordances", "spec, pool, *, instance, reserved="
    ),
    "aenforce_affordances": _fn(
        "affordances.aenforce_affordances", "spec, pool, *, instance, reserved="
    ),
    "operation_affordances": _fn("affordances.operation_affordances", "spec"),
    "unmet_operation_affordance": _fn(
        "affordances.unmet_operation_affordance", "spec, pool, *, reserved="
    ),
    "aunmet_operation_affordance": _fn(
        "affordances.aunmet_operation_affordance", "spec, pool, *, reserved="
    ),
    # --- authorization ------------------------------------------------------------------------
    "resolve_principal": _fn("authorization.resolve_principal", "identifier"),
    # Subclassed by the adapter's permission check over DRF permission classes.
    "PermissionCheck": Pin(
        "authorization.permission_check",
        abstract=frozenset({"has_permission"}),
        methods={
            "has_permission": "(principal, spec)",
            "has_object_permission": "(principal, spec, target)",
            "has_scope_permission": "(principal, spec, scope)",
        },
    ),
    "Unrestricted": Pin(
        "authorization.unrestricted",
        bases=("PermissionCheck",),
        methods={"has_permission": "(principal, spec)"},
    ),
    # The adapter subclasses these two beside DRF's PermissionDenied.
    "NotPermitted": _error("authorization.not_permitted", "message=", "DispatchError"),
    "PrincipalUnavailable": _error(
        "authorization.principal_unavailable", "message=", "DispatchError"
    ),
    # --- dispatch -----------------------------------------------------------------------------
    "dispatch": _fn(
        "dispatch.dispatch",
        "spec, *, principal, arguments, grant=, pool_seeds=, unknown_arguments=, progress=, "
        "target=, extra_kwargs=",
    ),
    "adispatch": _fn(
        "dispatch.adispatch",
        "spec, *, principal=, principal_id=, arguments, grant=, pool_seeds=, "
        "unknown_arguments=, progress=, target=, extra_kwargs=",
    ),
    "check_call": _fn(
        "dispatch.check_call",
        "spec, *, principal, arguments, grant=, pool_seeds=, unknown_arguments=",
    ),
    "check_requested_input": _fn("dispatch.check_requested_input", "spec, schema, *, pool_seeds="),
    "bind_arguments": _fn(
        "dispatch.bind_arguments", "spec, arguments, *, principal, target=, unknown_arguments="
    ),
    "resolve_target": _fn(
        "dispatch.resolve_target", "spec, *, principal, arguments, grant=, pool_seeds="
    ),
    "present": _fn("dispatch.present", "spec, result"),
    "apresent": _fn("dispatch.apresent", "spec, result"),
    "audience_projection_for_spec": _fn(
        "dispatch.audience_projection_for_spec", "spec, *, overrides=, name="
    ),
    "present_for_audience": _fn("dispatch.present_for_audience", "spec, result, *, projection="),
    "paginate_output": _fn("dispatch.paginate_output", "rows, *, page=, limit=, max_page_size="),
    "DEFAULT_PAGE_SIZE": Pin("dispatch.paginate_output", value=100),
    "DispatchResult": Pin(
        "dispatch.dispatch_result",
        signature="kind, value=, service_result=, instance=, data=, context=",
    ),
    "authorize": _fn("dispatch.authorize", "spec, principal, *, grant=, arguments="),
    "authorize_scope": _fn(
        "dispatch.authorize_scope", "spec, principal, scope, *, grant, arguments="
    ),
    "authorize_target": _fn(
        "dispatch.authorize_target", "spec, principal, target, *, grant, arguments="
    ),
    "Grant": Pin(
        "dispatch.grant",
        signature="spec, principal, target_checked=",
        methods={"covers": "(spec, principal)"},
    ),
    # --- adapters -----------------------------------------------------------------------------
    "filter_set_parameters": _fn("adapters.filters.filter_set_parameters", "filter_set"),
    # --- mutations ----------------------------------------------------------------------------
    "apply_input": _fn("mutations.apply_input", "instance, data, *, field_map=, exclude_fields="),
    "create_from_input": _fn(
        "mutations.create_from_input",
        "model, data, *, field_map=, exclude_fields=, m2m=, relations=, context=",
    ),
    "acreate_from_input": _fn(
        "mutations.acreate_from_input",
        "model, data, *, field_map=, exclude_fields=, m2m=, relations=, context=",
    ),
    "update_from_input": _fn(
        "mutations.update_from_input",
        "instance, data, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=, "
        "context=",
    ),
    "aupdate_from_input": _fn(
        "mutations.aupdate_from_input",
        "instance, data, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=, "
        "context=",
    ),
    "delete_relations": _fn("mutations.delete_relations", "instance, *, relations, context="),
    "adelete_relations": _fn("mutations.adelete_relations", "instance, *, relations, context="),
    # The seam the adapter fills with DRF's ValidationError from a row write.
    "register_row_error": _fn("mutations.register_row_error", "error_class, read_detail"),
    "ChangeResult": Pin(
        "mutations.change_result",
        signature="instance, created, changes, children=, relations=",
        methods={
            "changed_fields": "property",
            "get_field_change": "(field_name)",
            "get_child_change": "(relation)",
            "get_relation_change": "(relation)",
        },
    ),
    "ChildCollectionChange": Pin(
        "mutations.child_collection_change",
        signature="relation, created=, updated=, deleted=, unlinked=, removed=",
    ),
    # The adapter's own generic subclass of ChangeResult is parameterized with
    # this one, so a rename, a new bound or a second TypeVar breaks it.
    "ModelT": Pin(
        "mutations.change_result", leaf_only=True, bound=Model, parameter_of="ChangeResult"
    ),
    "FieldChange": Pin("mutations.field_change", signature="field, old, new"),
    "RelatedObjectChange": Pin(
        "mutations.related_object_change", signature="relation, outcome=, pk="
    ),
    "create_model": _fn(
        "mutations.create_model", "model, *, field_map=, exclude_fields=, m2m=, relations="
    ),
    "acreate_model": _fn(
        "mutations.acreate_model", "model, *, field_map=, exclude_fields=, m2m=, relations="
    ),
    "update_model": _fn(
        "mutations.update_model",
        "model, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=",
    ),
    "aupdate_model": _fn(
        "mutations.aupdate_model",
        "model, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=",
    ),
    "delete_model": _fn("mutations.delete_model", "model, *, soft_delete=, relations="),
    "adelete_model": _fn("mutations.adelete_model", "model, *, soft_delete=, relations="),
    "delete_collection": _fn("mutations.delete_collection", "model, *, soft_delete="),
    "adelete_collection": _fn("mutations.adelete_collection", "model, *, soft_delete="),
    # --- output -------------------------------------------------------------------------------
    "Output": Pin("output.output", signature="fields=", methods={"names": "()", "get": "(name)"}),
    "OutputField": Pin(
        "output.output",
        signature="name, type, *, format=, nullable=, label=, choices=, always_present=, "
        "marking=, fields=, items=, items_nullable=",
    ),
    # Subclassed by the adapter's serializer presenter.
    "Presenter": Pin(
        "output.presenter",
        abstract=frozenset({"output", "present"}),
        methods={"output": "()", "present": "(value)", "presented": "(value, context)"},
    ),
    # What the adapter's serializer presenter reads its serializer context from.
    "PresentationContext": Pin(
        "output.presentation_context", signature="principal, target=, ambient="
    ),
    "FieldMarking": Pin(
        "output.field_marking",
        signature="audience=, description=, formatter=",
        methods={
            "handle": "classmethod(description=)",
            "hidden": "classmethod()",
            "label": "classmethod(description=)",
            "formatted": "classmethod(formatter, description=)",
            "timestamp": "classmethod(fmt=, description=)",
        },
    ),
    "AudienceProjection": Pin(
        "output.audience_projection",
        signature="fields=, label=, choice_labels=, nested=",
        methods={"is_empty": "()", "audience": "(name)", "formatter": "(name)"},
    ),
    "annotate_output_schema": _fn(
        "output.annotate_output_schema", "schema, projection, *, handle_description="
    ),
    "project_payload": _fn("output.project_payload", "payload, projection"),
    # --- parameters ---------------------------------------------------------------------------
    "Parameter": Pin(
        "parameters.parameters",
        signature="name, type, *, required=, format=, items=, items_nullable=, fields=, "
        "choices=, choice_labels=, minimum=, maximum=, min_length=, max_length=, default=, "
        "nullable=, help=",
        methods={"nested": "property"},
    ),
    "Parameters": Pin(
        "parameters.parameters",
        signature="items=",
        methods={"names": "()", "get": "(name)", "of": "classmethod(*parameters)"},
    ),
    "check_arguments": _fn(
        "parameters.check_arguments", "parameters, arguments, *, unknown_arguments=, partial="
    ),
    "coerce_flat": _fn("parameters.coerce_flat", "parameters, raw"),
    # The adapter subclasses it beside DRF's ValidationError, and reads its detail.
    "InvalidArguments": _error("parameters.invalid_arguments", "detail", "DispatchError"),
    "CodedMessage": _error("parameters.coded_message", "message, code", str),
    "NON_FIELD_ERRORS": Pin("parameters.non_field_errors", value="non_field_errors"),
    # --- pool ---------------------------------------------------------------------------------
    "PoolSeeds": Pin(
        "pool.pool_seeds",
        signature="seeds=",
        methods={
            "extend": "(**seeds)",
            "names": "property",
            "reserved": "property",
            "resolvers": "()",
        },
    ),
    "DEFAULT_POOL_SEEDS": Pin("pool.pool_seeds", instance_of="PoolSeeds"),
    "RESERVED_POOL_SEEDS": Pin(
        "pool.reserved_pool_seeds",
        value=frozenset(
            {"user", "data", "instance", "collection", "result", "queryset", "progress"}
        ),
    ),
    "base_pool": _fn("pool.base_pool", "*, user, progress=, seeds=, **extra"),
    "combine_progress": _fn("pool.combine_progress", "*reporters"),
    "null_progress": _fn("pool.null_progress", "progress, *, total=, message=, meta="),
    "provider_keys": _fn("pool.provider_keys", "provider"),
    "resolve_callable_kwargs": _fn("pool.resolve_callable_kwargs", "fn, pool"),
    # --- registry -----------------------------------------------------------------------------
    "RegisteredSpec": Pin(
        "registry.registered_spec",
        signature="name, spec, tags=",
        methods={"agent_contract": "property"},
    ),
    "SpecRegistry": Pin(
        "registry.spec_registry",
        signature="entries=",
        methods={
            "register": "(name, spec, *, tags=)",
            "get": "(name)",
            "all": "()",
            "mutations": "()",
            "queries": "()",
            "by_tag": "(*tags)",
            "subset": "(*names)",
            "merge": "(*others)",
            "specs": "()",
            "__len__": "()",
            "__contains__": "(name)",
            "__iter__": "()",
        },
    ),
    # --- relations ----------------------------------------------------------------------------
    "RelationSpec": Pin("relations.relation_spec"),
    "ChildSpec": Pin(
        "relations.child_spec",
        signature="model, fk, *, match_key=, mode=, orphan=, field_map=, exclude_fields=, m2m=, "
        "relations=, create_service=, update_service=, delete_service=",
        bases=("RelationSpec",),
    ),
    "ForwardRelationSpec": Pin(
        "relations.forward_relation_spec",
        signature="model, *, match_key=, scope=, field_map=, exclude_fields=, m2m=, relations=, "
        "create_service=, update_service=",
        bases=("RelationSpec",),
    ),
    "GenericRelationSpec": Pin(
        "relations.generic_relation_spec",
        signature="model, *, content_type_field=, object_id_field=, match_key=, mode=, orphan=, "
        "field_map=, exclude_fields=, m2m=, relations=, create_service=, update_service=, "
        "delete_service=",
        bases=("RelationSpec",),
    ),
    "ManyToManySpec": Pin(
        "relations.many_to_many_spec",
        signature="model, *, match_key=, scope=, mode=, field_map=, exclude_fields=, m2m=, "
        "relations=, create_service=, update_service=",
        bases=("RelationSpec",),
    ),
    "ReverseOneToOneSpec": Pin(
        "relations.reverse_one_to_one_spec",
        signature="model, fk, *, orphan=, field_map=, exclude_fields=, m2m=, relations=, "
        "create_service=, update_service=, delete_service=",
        bases=("RelationSpec",),
    ),
    # --- schema -------------------------------------------------------------------------------
    "can_present_nothing": _fn("schema.can_present_nothing", "spec"),
    "output_schema": _fn("schema.output_schema", "output"),
    "parameters_schema": _fn("schema.parameters_schema", "parameters, *, unknown_arguments="),
    "spec_input_schema": _fn("schema.spec_input_schema", "spec, *, unknown_arguments="),
    "spec_output_schema": _fn(
        "schema.spec_output_schema", "spec, *, paginate=, projection=, handle_description="
    ),
    # --- selectors ----------------------------------------------------------------------------
    "Selector": _protocol("selectors.selector", "(*args, **kwargs)"),
    "AsyncSelector": _protocol("selectors.async_selector", "(*args, **kwargs)"),
    "ListSelector": _protocol("selectors.list_selector", "(**extras)"),
    "RetrieveSelector": _protocol("selectors.retrieve_selector", "(**extras)"),
    "run_selector": _fn("selectors.run_selector", "fn, kwargs"),
    "arun_selector": _fn("selectors.arun_selector", "fn, kwargs"),
    "materialize_retrieve": _fn("selectors.materialize_retrieve", "result"),
    "amaterialize_retrieve": _fn("selectors.amaterialize_retrieve", "result"),
    "is_queryset": _fn("selectors.is_queryset", "obj"),
    "shape_queryset": _fn("selectors.shape_queryset", "queryset, spec, pool, *, source_label"),
    # --- services -----------------------------------------------------------------------------
    "ServiceError": _error("services.service_error", "message=", Exception),
    "ServiceConflict": _error("services.service_conflict", "message=", "ServiceError"),
    "ServiceNotFound": _error("services.service_not_found", "message=", "ServiceError"),
    "ActionUnavailable": _error(
        "services.action_unavailable", "message=, *, code", "ServiceConflict"
    ),
    "AdditionalInputRequired": _error(
        "services.additional_input_required", "message, *, schema=", "ServiceError"
    ),
    "ServiceValidationError": _error("services.service_validation_error", "detail", "ServiceError"),
    "CreateService": _protocol("services.create_service", "(*, data, **extras)"),
    "UpdateService": _protocol("services.update_service", "(*, instance, data, **extras)"),
    "DeleteService": _protocol("services.delete_service", "(*, instance, data=, **extras)"),
    "implements": _fn("services.implements", "proto"),
    "run_service": _fn("services.run_service", "fn, kwargs, *, atomic"),
    "arun_service": _fn("services.arun_service", "fn, kwargs, *, atomic"),
    # --- specs --------------------------------------------------------------------------------
    # The adapter's spec classes compile to these two through the seam below.
    "ServiceSpec": Pin(
        "specs.service_spec",
        signature="*, service, permissions=, reads=, partial=, many=, many_argument=, "
        "many_min_length=, many_max_length=, validator=, instance_selector_spec=, "
        "collection_selector_spec=, output_selector_spec=, presenter=, allow_none=, "
        "affordances=, atomic=, idempotent=, preconditions=, kwargs=, input_data=, "
        "progress_reporter=, metadata=",
        methods={
            "parameters": "()",
            "output": "()",
            "target_selector_spec": "()",
            "presenter_for_output": "()",
        },
    ),
    "SelectorSpec": Pin(
        "specs.selector_spec",
        signature="*, kind, selector, permissions=, reads=, presenter=, allow_none=, "
        "select_related=, prefetch_related=, annotations=, extend_queryset=, filter_set=, "
        "affordances=, kwargs=, preconditions=, progress_reporter=, metadata=",
        methods={"parameters": "()", "output": "()"},
    ),
    "SpecSource": Pin("specs.spec_source", methods={"as_kernel_spec": "()"}),
    "kernel_spec": _fn("specs.kernel_spec", "spec"),
    "server_owned_keys": _fn("specs.server_owned_keys", "spec, *, pool_seeds="),
    # --- types --------------------------------------------------------------------------------
    "DispatchError": _error("types.dispatch_error", "message=", Exception),
    "Affordance": Pin("types.affordance", signature="code, reason, when"),
    "NoInput": Pin("types.no_input"),
    "OutputPage": Pin(
        "types.output_page",
        signature="items, page, limit, total",
        methods={"total_pages": "property", "has_next": "property", "envelope": "(rendered)"},
    ),
    "ProgressReporter": _protocol(
        "types.progress_reporter", "(progress, *, total=, message=, meta=)"
    ),
    "ProviderKeys": Pin("types.provider_keys", signature="filled, declinable", bases=(tuple,)),
    "UNSET": Pin("types.unset", instance_of="UnsetType"),
    "UnsetType": Pin("types.unset"),
    "ValueFormatter": Pin(
        "types.value_formatter",
        signature="render, produces, schema=",
        methods={"apply": "(value)", "json_schema": "()", "timestamp": "classmethod(fmt=)"},
    ),
    "RelationOutcome": _enum(
        "types.relation_outcome",
        {
            "UNTOUCHED": "untouched",
            "CREATED": "created",
            "UPDATED": "updated",
            "CLEARED": "cleared",
            "UNLINKED": "unlinked",
            "DELETED": "deleted",
            "REMOVED": "removed",
        },
        str,
    ),
    "FieldAudience": _enum(
        "types.field_audience",
        {"CONTENT": "content", "LABEL": "label", "HANDLE": "handle", "HIDDEN": "hidden"},
        str,
    ),
    "RelationMode": _enum("types.relation_mode", {"REPLACE": "replace", "MERGE": "merge"}, str),
    "RelationOrphan": _enum(
        "types.relation_orphan", {"AUTO": "auto", "UNLINK": "unlink", "DELETE": "delete"}, str
    ),
    "RelationPhase": _enum(
        "types.relation_phase", {"FORWARD": 0, "REVERSE": 1, "GENERIC": 2, "M2M": 3}, int
    ),
    "is_async": _fn("types.is_async", "fn"),
    "SelectorKind": _enum("types.selector_kind", {"LIST": "list", "RETRIEVE": "retrieve"}, str),
    # The compile seam: every entry point takes an object answering as_kernel_spec().
    "UnknownArguments": _enum(
        "types.unknown_arguments",
        {"REJECT": "reject", "IGNORE": "ignore", "PASSTHROUGH": "passthrough"},
        str,
    ),
    # Subclassed by the adapter's serializer validator.
    # --- validation ---------------------------------------------------------------------------
    "Validator": Pin(
        "validation.validator",
        abstract=frozenset({"parameters", "validate"}),
        methods={
            "parameters": "()",
            "validate": "(arguments, context)",
            "validated": "(arguments, context)",
            "validated_many": "(rows, context, *, many_argument)",
        },
    ),
    "ValidationContext": Pin(
        "validation.validation_context", signature="principal, target=, partial=, ambient="
    ),
    "Validated": Pin("validation.validated", signature="values, data, pool="),
    # --- http: the two helpers a non-DRF HTTP transport reaches for ----------------------------
    "request_principal": _fn("http.request_principal", "request"),
    "route_arguments": _fn("http.route_arguments", "parameters, url_kwargs"),
}

# Public here and taken by nobody downstream through djangorestframework-services,
# which has its own HTTP views and its own serializer adapters. Each is a decision:
# a new root name lands in SURFACE or here, never in neither.
NOT_REEXPORTED_BY_DRFS = frozenset(
    {
        # This package's own JSON transport: djangorestframework-services serves
        # HTTP through DRF's views, never through these.
        "SpecView",
        "AsyncSpecView",
        # A management command over a registry: a transport of this package's,
        # which drfs reaches only by compiling its specs into a registry.
        "SpecCommand",
        # Its exit statuses, and the refusal each ends a run with.
        "ExitCode",
        "exit_code_for",
        # How that command writes a presented result to a terminal or a pipe.
        # drfs presents through DRF's renderers and has no command of its own.
        "render_result",
        "render_table",
        "render_json_lines",
        "wants_table",
        # The argv layer that command is built from, which only a command reads.
        "ParameterDescriptor",
        "describe_parameters",
        "add_spec_arguments",
        "parsed_arguments",
        # The report of a registry's open specs, read by that command and by the
        # system check its app registers; drfs serves no management command.
        "UnguardedReason",
        "UnguardedSpec",
        "unguarded_message",
        "unguarded_specs",
        "UnsupportedMediaType",
        "dispatch_request",
        # The shared check that a transport's refusal map answers every kernel
        # refusal: a transport's own suite reads these from the kernel, and a
        # drfs consumer writes no refusal map.
        "REFUSALS",
        "unanswered_refusals",
        "adispatch_request",
        "error_response",
        "add_argument_errors",
        "request_arguments",
        # Adapters over dataclasses and Django forms: the DRF adapter is its
        # serializer validator and presenter, which subclass Validator and
        # Presenter above instead.
        "DataclassPresenter",
        "DataclassValidator",
        "FormValidator",
        # A transport's binding of declared parameters to server values: the
        # transports that bind call these from this package, and
        # djangorestframework-services neither wraps nor re-exports them. A
        # drfs release that starts to take them moves them into the pinned table.
        "ServerArguments",
        "check_server_arguments",
        "apply_server_arguments",
        # This package's version, which no importer reads as an API.
        "__version__",
    }
)


def _render(signature: inspect.Signature, *, bound: bool) -> str:
    """``signature`` as names, kinds and default-or-not, in Python's own notation.

    ``bound`` drops the first parameter, the ``self`` of a method read off the
    class. A parameter named with a leading underscore is the declaring
    class's own (a dataclass's private field) and no caller passes it, so it
    is left out.
    """
    parameters = list(signature.parameters.values())[1 if bound else 0 :]
    parts: list[str] = []
    star = False
    for index, parameter in enumerate(parameters):
        if parameter.name.startswith("_"):
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not star:
            parts.append("*")
            star = True
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"*{parameter.name}")
            star = True
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            parts.append(f"**{parameter.name}")
        else:
            default = "=" if parameter.default is not inspect.Parameter.empty else ""
            parts.append(f"{parameter.name}{default}")
        following = parameters[index + 1].kind if index + 1 < len(parameters) else None
        if (
            parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            and following is not inspect.Parameter.POSITIONAL_ONLY
        ):
            parts.append("/")
    return ", ".join(parts)


def _method(owner: type, name: str) -> str:
    """How ``owner.name`` is called: ``property``, ``classmethod(...)`` or ``(...)``."""
    attribute = inspect.getattr_static(owner, name)
    if isinstance(attribute, property):
        return "property"
    if isinstance(attribute, classmethod):
        return f"classmethod({_render(inspect.signature(getattr(owner, name)), bound=False)})"
    if isinstance(attribute, staticmethod):
        return f"staticmethod({_render(inspect.signature(getattr(owner, name)), bound=False)})"
    return f"({_render(inspect.signature(attribute), bound=True)})"


def _resolve(base: str | type) -> type:
    return getattr(django_service_specs, base) if isinstance(base, str) else base


def _rows(facet: str) -> list[str]:
    """The names whose row pins ``facet``, which is every row whose value differs from a bare pin's."""
    unpinned = getattr(Pin(""), facet)
    return [name for name, pin in SURFACE.items() if getattr(pin, facet) != unpinned]


# --- the table holds ----------------------------------------------------------------------------


def _leaf_value(name: str) -> Any:
    return getattr(importlib.import_module(f"{_PACKAGE}.{SURFACE[name].leaf}"), name)


@pytest.mark.parametrize("name", [name for name, pin in SURFACE.items() if not pin.leaf_only])
def test_importable_from_the_root_its_subpackage_and_its_leaf(name: str) -> None:
    leaf = SURFACE[name].leaf
    subpackage = importlib.import_module(f"{_PACKAGE}.{leaf.rpartition('.')[0]}")
    # import_module rather than attribute access: a subpackage re-exporting a
    # function named after its module shadows that module as an attribute.
    module = importlib.import_module(f"{_PACKAGE}.{leaf}")

    exported = getattr(django_service_specs, name)
    assert name in django_service_specs.__all__
    assert name in subpackage.__all__
    assert getattr(subpackage, name) is exported
    assert getattr(module, name) is exported


@pytest.mark.parametrize("name", _rows("leaf_only"))
def test_a_leaf_only_name_is_importable_from_its_leaf_alone(name: str) -> None:
    subpackage = importlib.import_module(f"{_PACKAGE}.{SURFACE[name].leaf.rpartition('.')[0]}")
    _leaf_value(name)
    assert name not in django_service_specs.__all__
    assert name not in subpackage.__all__


@pytest.mark.parametrize("name", _rows("bound"))
def test_a_type_variable_as_pinned(name: str) -> None:
    pin = SURFACE[name]
    type_var = _leaf_value(name)
    assert isinstance(type_var, TypeVar)
    assert type_var.__name__ == name
    assert type_var.__bound__ is pin.bound
    assert pin.parameter_of is not None
    assert getattr(django_service_specs, pin.parameter_of).__parameters__ == (type_var,)


@pytest.mark.parametrize("name", _rows("signature"))
def test_called_as_pinned(name: str) -> None:
    exported = getattr(django_service_specs, name)
    assert _render(inspect.signature(exported), bound=False) == SURFACE[name].signature


@pytest.mark.parametrize("name", _rows("methods"))
def test_methods_called_as_pinned(name: str) -> None:
    owner = getattr(django_service_specs, name)
    pinned = SURFACE[name].methods
    assert {method: _method(owner, method) for method in pinned} == dict(pinned)


@pytest.mark.parametrize("name", _rows("abstract"))
def test_a_subclass_owes_only_the_pinned_abstract_methods(name: str) -> None:
    # A new abstract method breaks every subclass downstream at instantiation,
    # which no signature pin would see.
    assert getattr(django_service_specs, name).__abstractmethods__ == SURFACE[name].abstract


@pytest.mark.parametrize("name", _rows("bases"))
def test_keeps_its_pinned_bases(name: str) -> None:
    # An exception ladder catching the base, and a class subclassing this one
    # beside another library's, both rest on the hierarchy.
    exported = getattr(django_service_specs, name)
    for base in SURFACE[name].bases:
        assert issubclass(exported, _resolve(base)), base


@pytest.mark.parametrize("name", _rows("members"))
def test_enum_members_as_pinned(name: str) -> None:
    exported = getattr(django_service_specs, name)
    assert issubclass(exported, enum.Enum)
    # Iteration skips an alias, so a member redefined as another's value fails.
    assert {member.name: member.value for member in exported} == dict(SURFACE[name].members or {})


@pytest.mark.parametrize("name", _rows("value"))
def test_constant_value_as_pinned(name: str) -> None:
    assert getattr(django_service_specs, name) == SURFACE[name].value


@pytest.mark.parametrize("name", _rows("instance_of"))
def test_value_of_the_pinned_type(name: str) -> None:
    pinned = SURFACE[name].instance_of
    assert pinned is not None
    assert isinstance(getattr(django_service_specs, name), _resolve(pinned))


@pytest.mark.parametrize(
    ("name", "args", "kwargs", "attributes"),
    [
        ("DispatchError", (), {}, {"message", "default_message"}),
        ("NotPermitted", (), {}, {"message", "default_message"}),
        ("PrincipalUnavailable", (), {}, {"message", "default_message"}),
        ("InvalidArguments", ({"title": ["Required."]},), {}, {"detail", "message"}),
        ("ServiceError", (), {}, {"message", "default_message"}),
        ("ServiceConflict", (), {}, {"message", "default_message"}),
        ("ServiceNotFound", (), {}, {"message", "default_message"}),
        ("ActionUnavailable", (), {"code": "closed"}, {"message", "code"}),
        ("AdditionalInputRequired", ("Confirm?",), {"schema": {}}, {"message", "schema"}),
        ("ServiceValidationError", ({"title": ["Taken."]},), {}, {"detail", "message"}),
    ],
)
def test_exceptions_carry_what_a_translator_reads(
    name: str, args: tuple[Any, ...], kwargs: dict[str, Any], attributes: set[str]
) -> None:
    # A translator re-raising these as DRF's exceptions, and a transport's
    # exception ladder, read these attributes off the instance.
    raised = getattr(django_service_specs, name)(*args, **kwargs)
    assert {attribute for attribute in attributes if hasattr(raised, attribute)} == attributes


# --- the table is complete ----------------------------------------------------------------------


def test_every_root_name_is_pinned_or_named_as_not_taken() -> None:
    exported = set(django_service_specs.__all__)
    assert exported - set(SURFACE) - NOT_REEXPORTED_BY_DRFS == set()


def test_no_name_is_both_pinned_and_named_as_not_taken() -> None:
    assert set(SURFACE) & NOT_REEXPORTED_BY_DRFS == set()


def test_every_name_held_out_is_still_public() -> None:
    # A stale entry would let a later name of the same spelling through unpinned.
    assert NOT_REEXPORTED_BY_DRFS - set(django_service_specs.__all__) == set()


# --- the rendering the pins are read through ----------------------------------------------------


def _positional_only(a: int, /, b: int) -> None: ...


def _everything(a: int, b: int = 0, *args: int, c: int, d: int = 0, **kwargs: int) -> None: ...


def _keyword_only(*, a: int) -> None: ...


def _private_tail(a: int, *, _hidden: int = 0) -> None: ...


@pytest.mark.parametrize(
    ("function", "rendered"),
    [
        (_positional_only, "a, /, b"),
        (_everything, "a, b=, *args, c, d=, **kwargs"),
        (_keyword_only, "*, a"),
        (_private_tail, "a"),
    ],
)
def test_the_rendering_tells_every_kind_apart(function: Any, rendered: str) -> None:
    # The pins are only as strict as this rendering: a parameter made
    # keyword-only, given or stripped of a default, or renamed must read
    # differently, or the table would pass a change it exists to catch.
    assert _render(inspect.signature(function), bound=False) == rendered


def test_the_rendering_tells_method_kinds_apart() -> None:
    class Owner:
        def method(self, a: int) -> None: ...

        @classmethod
        def made(cls, a: int) -> None: ...

        @staticmethod
        def plain(a: int) -> None: ...

        @property
        def value(self) -> int:
            return 0

    assert [_method(Owner, name) for name in ("method", "made", "plain", "value")] == [
        "(a)",
        "classmethod(a)",
        "staticmethod(a)",
        "property",
    ]


# --- the registry entry's agent_contract --------------------------------------------------------
#
# The published MCP and agent transports read ``entry.agent_contract`` off a
# registry entry. djangorestframework-services answers it from its own spec
# while that release is current, so the entry must keep asking the object as
# registered rather than storing a value of its own.


def _open_selector(selector: Any = None) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=selector if selector is not None else _no_rows,
        permissions=[Unrestricted()],
    )


def _no_rows() -> list[Any]:
    return []


class _CompilesWithContract:
    """Shaped as djangorestframework-services' spec where the entry reads it."""

    def __init__(self, contract: object) -> None:
        self.contract = contract

    def as_kernel_spec(self) -> SelectorSpec:
        return _open_selector()

    def agent_contract(self) -> object:
        return self.contract


def test_the_entry_answers_the_registered_object_s_agent_contract() -> None:
    contract = object()
    registry = SpecRegistry()
    registry.register("list_notes", _CompilesWithContract(contract))

    assert registry.get("list_notes").agent_contract is contract


class _CompilesWithoutContract:
    """The same spec once it stops carrying a contract, as it will in a later release."""

    def as_kernel_spec(self) -> SelectorSpec:
        return _open_selector()


class _HoldsAContractValue(_CompilesWithoutContract):
    """An ``agent_contract`` that is a value rather than the method: not asked."""

    agent_contract = "a value, not the method"


@pytest.mark.parametrize(
    "registered",
    [_open_selector, _CompilesWithoutContract, _HoldsAContractValue],
    ids=["kernel spec", "source without one", "source holding a value"],
)
def test_the_entry_answers_none_for_anything_without_the_method(registered: Any) -> None:
    registry = SpecRegistry()
    registry.register("list_notes", registered())

    assert registry.get("list_notes").agent_contract is None


def test_the_entry_s_agent_contract_is_a_property_without_a_setter() -> None:
    # Assigning to the entry proves nothing here: the entry is a frozen
    # dataclass, so any assignment raises, whatever agent_contract is. That
    # it is no field, which a registration could fill, is the signature row
    # for RegisteredSpec above.
    attribute = inspect.getattr_static(django_service_specs.RegisteredSpec, "agent_contract")
    assert isinstance(attribute, property)
    assert attribute.fset is None


def test_register_refuses_agent_contract_with_python_s_own_type_error() -> None:
    with pytest.raises(TypeError, match="agent_contract") as refused:
        SpecRegistry().register(
            "list_notes",
            _open_selector(),
            agent_contract=object(),  # type: ignore[call-arg]
        )
    # Plain TypeError, the one an unexpected keyword raises, rather than a
    # refusal of this package's own that a caller might catch by name.
    assert type(refused.value) is TypeError


# --- UnknownArguments.PASSTHROUGH ---------------------------------------------------------------
#
# The published MCP transport tests ``unknown_arguments is
# UnknownArguments.PASSTHROUGH`` on a policy it was configured with. The member
# keeps that line evaluating to False for IGNORE, where a missing member would
# raise AttributeError; as a policy it is refused everywhere one is read.

_REFUSED = r"UnknownArguments\.PASSTHROUGH is refused"


def test_passthrough_is_a_member_of_its_own() -> None:
    passthrough = UnknownArguments.PASSTHROUGH
    assert passthrough.value == "passthrough"
    assert UnknownArguments("passthrough") is passthrough
    # An alias of IGNORE would make the transport's test true and change
    # which branch it takes; iteration skips aliases.
    assert passthrough in list(UnknownArguments)
    configured = UnknownArguments.IGNORE
    assert (configured is UnknownArguments.PASSTHROUGH) is False


def test_dispatch_refuses_passthrough_rather_than_running_it_as_ignore() -> None:
    calls: list[int] = []

    def notes() -> list[Any]:
        calls.append(1)
        return []

    spec = _open_selector(notes)
    # Sized so the policy answers: an anonymous principal no deactivation
    # check refuses, an open spec, and a key no parameter declares, which
    # IGNORE drops and runs.
    dispatch(
        spec,
        principal=AnonymousUser(),
        arguments={"tenant": "acme"},
        unknown_arguments=UnknownArguments.IGNORE,
    )
    assert calls == [1]

    with pytest.raises(ValueError, match=_REFUSED):
        dispatch(
            spec,
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )
    assert calls == [1]


async def test_adispatch_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        await adispatch(
            _open_selector(),
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


def test_check_call_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        check_call(
            _open_selector(),
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


def test_check_arguments_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        check_arguments(
            Parameters(), {"tenant": "acme"}, unknown_arguments=UnknownArguments.PASSTHROUGH
        )


def test_parameters_schema_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        parameters_schema(Parameters(), unknown_arguments=UnknownArguments.PASSTHROUGH)
