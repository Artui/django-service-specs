"""Running a ``SelectorSpec``'s selector, and shaping and collapsing what it returns."""

from django_service_specs.selectors.amaterialize_retrieve import amaterialize_retrieve
from django_service_specs.selectors.arun_selector import arun_selector
from django_service_specs.selectors.async_selector import AsyncSelector
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.list_selector import ListSelector
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.retrieve_selector import RetrieveSelector
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.selector import Selector
from django_service_specs.selectors.shape_queryset import shape_queryset

__all__ = [
    "AsyncSelector",
    "ListSelector",
    "RetrieveSelector",
    "Selector",
    "amaterialize_retrieve",
    "arun_selector",
    "is_queryset",
    "materialize_retrieve",
    "run_selector",
    "shape_queryset",
]
