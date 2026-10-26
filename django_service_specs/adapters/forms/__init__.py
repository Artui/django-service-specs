"""A Django form class as a Validator, and its keywords for a form built off dispatch."""

from django_service_specs.adapters.forms.form_keywords import form_keywords
from django_service_specs.adapters.forms.form_validator import FormValidator

__all__ = ["FormValidator", "form_keywords"]
