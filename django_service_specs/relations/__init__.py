"""How a nested write persists each kind of relation: the five relation specs."""

from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.relation_mode import RelationMode
from django_service_specs.relations.relation_orphan import RelationOrphan
from django_service_specs.relations.relation_phase import RelationPhase
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec

__all__ = [
    "ChildSpec",
    "ForwardRelationSpec",
    "GenericRelationSpec",
    "ManyToManySpec",
    "RelationMode",
    "RelationOrphan",
    "RelationPhase",
    "RelationSpec",
    "ReverseOneToOneSpec",
]
