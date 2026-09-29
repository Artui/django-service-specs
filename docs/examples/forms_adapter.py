"""The forms adapter: a plain form as a Validator, and a ModelForm behind an update."""

from __future__ import annotations

# --8<-- [start:form]
from typing import Any

from django import forms
from django.contrib.auth import get_user_model

from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    update_from_input,
)
from django_service_specs.adapters.forms import FormValidator
from tests.adapter_app.models import Author, Status


class BookForm(forms.Form):
    title = forms.CharField(max_length=100, help_text="As printed on the cover.")
    price = forms.DecimalField(max_digits=6, decimal_places=2)
    status = forms.ChoiceField(choices=Status.choices)
    published_on = forms.DateField(required=False)
    author = forms.ModelChoiceField(queryset=Author.objects.all())
    shelves = forms.MultipleChoiceField(
        choices=[("fiction", "Fiction"), ("poetry", "Poetry")], required=False
    )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if cleaned.get("status") == Status.PUBLISHED and not cleaned.get("published_on"):
            raise forms.ValidationError("A published book needs its publication date.")
        return cleaned


# The form is read here, once: a field with no JSON type fails on this line.
book_validator = FormValidator(BookForm)
# --8<-- [end:form]


# --8<-- [start:model_form]
User = get_user_model()


class UsernameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]  # unique on the model


class IsThemselves(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return principal.is_authenticated

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return target.pk == principal.pk


def rename_user(*, instance: Any, data: dict[str, Any]) -> Any:
    # Saves only the fields whose value changed, which is why the form never
    # writes to ``instance`` itself: it validates against a copy.
    return update_from_input(instance, data).instance


rename_user_spec = ServiceSpec(
    service=rename_user,
    permissions=[IsThemselves()],
    validator=FormValidator(UsernameForm),
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: User.objects.filter(pk=pk),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
)
# --8<-- [end:model_form]
