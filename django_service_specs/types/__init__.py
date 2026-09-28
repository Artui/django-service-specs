"""Value-shape carriers shared across the package, and the root of its refusals."""

from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unset import UNSET, UnsetType

__all__ = ["UNSET", "DispatchError", "UnsetType"]
