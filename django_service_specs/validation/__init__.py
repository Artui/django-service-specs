"""The Validator contract: what a Validator is handed, and what validation hands the operation."""

from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

__all__ = ["Validated", "ValidationContext", "Validator"]
