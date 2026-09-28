"""A service contract for Django, dispatched from any transport."""

from django_service_specs.adapters.dataclass.dataclass_presenter import DataclassPresenter
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.apply_input import apply_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.mutations.child_collection_change import ChildCollectionChange
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.field_change import FieldChange
from django_service_specs.mutations.related_object_change import RelatedObjectChange
from django_service_specs.mutations.relation_outcome import RelationOutcome
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
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
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.services.arun_service import arun_service
from django_service_specs.services.is_async import is_async
from django_service_specs.services.run_service import run_service
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from django_service_specs.version import __version__

__all__ = [
    "ChangeResult",
    "ChildCollectionChange",
    "ChildSpec",
    "DEFAULT_POOL_SEEDS",
    "DataclassPresenter",
    "DataclassValidator",
    "DispatchError",
    "DispatchResult",
    "FieldAudience",
    "FieldChange",
    "FieldMarking",
    "ForwardRelationSpec",
    "GenericRelationSpec",
    "Grant",
    "InvalidArguments",
    "ManyToManySpec",
    "NotPermitted",
    "Output",
    "OutputField",
    "Parameter",
    "Parameters",
    "PermissionCheck",
    "PoolSeeds",
    "Presenter",
    "PrincipalUnavailable",
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
    "UNSET",
    "UnknownArguments",
    "Unrestricted",
    "UnsetType",
    "ValidationContext",
    "Validator",
    "__version__",
    "acreate_from_input",
    "apply_input",
    "arun_service",
    "aupdate_from_input",
    "authorize",
    "authorize_target",
    "base_pool",
    "bind_arguments",
    "check_arguments",
    "coerce_flat",
    "create_from_input",
    "is_async",
    "resolve_callable_kwargs",
    "resolve_principal",
    "run_service",
    "shape_queryset",
    "update_from_input",
]
