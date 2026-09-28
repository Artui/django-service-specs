"""Running one operation, from any transport."""

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present

__all__ = ["DispatchResult", "adispatch", "apresent", "bind_arguments", "dispatch", "present"]
