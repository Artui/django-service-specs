"""Mutation helpers: apply validated values to model rows, with change tracking.

Services call them explicitly inside their own bodies; dispatch never calls
them implicitly. Each returns a ``ChangeResult`` saying what the write did,
field by field and relation by relation.
"""

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

__all__ = [
    "ChangeResult",
    "ChildCollectionChange",
    "FieldChange",
    "RelatedObjectChange",
    "RelationOutcome",
    "acreate_from_input",
    "apply_input",
    "aupdate_from_input",
    "create_from_input",
    "update_from_input",
]
