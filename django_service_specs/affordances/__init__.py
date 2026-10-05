"""What can be done right now: answering a spec's affordances, at the call and before it."""

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)

__all__ = ["enforce_affordances", "operation_affordances", "unmet_operation_affordance"]
