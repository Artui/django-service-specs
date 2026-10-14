"""A service contract for Django, dispatched from any transport."""

from django_service_specs.adapters.dataclass.dataclass_presenter import DataclassPresenter
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.authorize_scope import authorize_scope
from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.paginate_output import DEFAULT_PAGE_SIZE, paginate_output
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.present_for_audience import present_for_audience
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.http.add_argument_errors import add_argument_errors
from django_service_specs.http.adispatch_request import adispatch_request
from django_service_specs.http.async_spec_view import AsyncSpecView
from django_service_specs.http.dispatch_request import dispatch_request
from django_service_specs.http.error_response import error_response
from django_service_specs.http.request_arguments import request_arguments
from django_service_specs.http.request_principal import request_principal
from django_service_specs.http.route_arguments import route_arguments
from django_service_specs.http.spec_view import SpecView
from django_service_specs.http.unsupported_media_type import UnsupportedMediaType
from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.adelete_relations import adelete_relations
from django_service_specs.mutations.apply_input import apply_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.mutations.child_collection_change import ChildCollectionChange
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.delete_relations import delete_relations
from django_service_specs.mutations.field_change import FieldChange
from django_service_specs.mutations.related_object_change import RelatedObjectChange
from django_service_specs.mutations.relation_outcome import RelationOutcome
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.output.project_payload import project_payload
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.registry.registered_spec import RegisteredSpec
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.relation_mode import RelationMode
from django_service_specs.relations.relation_orphan import RelationOrphan
from django_service_specs.relations.relation_phase import RelationPhase
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.selectors.amaterialize_retrieve import amaterialize_retrieve
from django_service_specs.selectors.arun_selector import arun_selector
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.arun_service import arun_service
from django_service_specs.services.is_async import is_async
from django_service_specs.services.run_service import run_service
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.output_page import OutputPage
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.types.value_formatter import ValueFormatter
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from django_service_specs.version import __version__

__all__ = [
    "ActionUnavailable",
    "AdditionalInputRequired",
    "Affordance",
    "AsyncSpecView",
    "AudienceProjection",
    "ChangeResult",
    "ChildCollectionChange",
    "ChildSpec",
    "CodedMessage",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_POOL_SEEDS",
    "DataclassPresenter",
    "DataclassValidator",
    "DispatchError",
    "DispatchResult",
    "FieldAudience",
    "FieldChange",
    "FieldMarking",
    "FormValidator",
    "ForwardRelationSpec",
    "GenericRelationSpec",
    "Grant",
    "InvalidArguments",
    "ManyToManySpec",
    "NotPermitted",
    "Output",
    "OutputField",
    "OutputPage",
    "Parameter",
    "Parameters",
    "PermissionCheck",
    "PoolSeeds",
    "Presenter",
    "PrincipalUnavailable",
    "ProgressReporter",
    "ProviderKeys",
    "RESERVED_POOL_SEEDS",
    "RegisteredSpec",
    "RelatedObjectChange",
    "RelationMode",
    "RelationOrphan",
    "RelationOutcome",
    "RelationPhase",
    "RelationSpec",
    "ReverseOneToOneSpec",
    "SelectorKind",
    "SelectorSpec",
    "ServiceConflict",
    "ServiceError",
    "ServiceNotFound",
    "ServiceSpec",
    "ServiceValidationError",
    "SpecRegistry",
    "SpecView",
    "UNSET",
    "UnknownArguments",
    "Unrestricted",
    "UnsetType",
    "UnsupportedMediaType",
    "ValidationContext",
    "Validated",
    "Validator",
    "ValueFormatter",
    "__version__",
    "acreate_from_input",
    "add_argument_errors",
    "adelete_relations",
    "adispatch",
    "adispatch_request",
    "amaterialize_retrieve",
    "annotate_output_schema",
    "apply_input",
    "apresent",
    "arun_selector",
    "arun_service",
    "audience_projection_for_spec",
    "aupdate_from_input",
    "authorize",
    "authorize_scope",
    "authorize_target",
    "base_pool",
    "bind_arguments",
    "check_arguments",
    "coerce_flat",
    "create_from_input",
    "delete_relations",
    "dispatch",
    "dispatch_request",
    "enforce_affordances",
    "error_response",
    "filter_set_parameters",
    "is_async",
    "is_queryset",
    "materialize_retrieve",
    "null_progress",
    "provider_keys",
    "operation_affordances",
    "output_schema",
    "paginate_output",
    "parameters_schema",
    "present",
    "present_for_audience",
    "project_payload",
    "request_arguments",
    "request_principal",
    "resolve_callable_kwargs",
    "server_owned_keys",
    "resolve_principal",
    "resolve_target",
    "route_arguments",
    "run_selector",
    "run_service",
    "shape_queryset",
    "spec_input_schema",
    "spec_output_schema",
    "unmet_operation_affordance",
    "update_from_input",
]
