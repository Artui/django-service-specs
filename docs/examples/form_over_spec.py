from __future__ import annotations

# --8<-- [start:held]
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from annotated_types import MaxLen
from django import forms
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import DataclassValidator, FormValidator, Validator, constraints_not_held
from tests.adapter_app.models import Book, Status


class BookPageForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["title", "price", "status"]


@dataclass
class BookLoose:
    title: str
    price: Decimal
    status: str = Status.DRAFT


@dataclass
class BookHeld:
    title: Annotated[str, MaxLen(100)]
    price: Decimal
    status: Status = Status.DRAFT


def check_page(form_class: type[forms.BaseForm], validator: Validator) -> None:
    spec = validator.parameters()
    found = [
        message
        for stated in FormValidator(form_class).parameters()
        if (held := spec.get(stated.name)) is not None
        for message in constraints_not_held(held, stated)
    ]
    if found:
        raise ImproperlyConfigured(" ".join(found))


loose_validator = DataclassValidator(BookLoose)
held_validator = DataclassValidator(BookHeld)
# --8<-- [end:held]
