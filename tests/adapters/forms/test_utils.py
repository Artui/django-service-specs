from __future__ import annotations

from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.forms.utils import BOUND_KEYWORDS, extra_keywords
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.validation.validation_context import ValidationContext


class _Plain(forms.Form):
    title = forms.CharField()


def test_no_form_kwargs_is_no_keywords() -> None:
    assert extra_keywords(_Plain, None, ValidationContext(object())) == {}


def test_it_binds_from_the_context_s_principal_and_the_no_op_reporter() -> None:
    principal = object()

    def asked(*, user: Any, progress: Any) -> dict[str, Any]:
        return {"user": user, "progress": progress}

    keywords = extra_keywords(_Plain, asked, ValidationContext(principal))
    assert keywords == {"user": principal, "progress": null_progress}


@pytest.mark.parametrize("key", sorted(BOUND_KEYWORDS))
def test_a_key_the_bind_sets_itself_is_refused_by_name(key: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=f"form_kwargs returned {key!r}, which"):
        extra_keywords(_Plain, lambda: {key: None}, ValidationContext(object()))


def test_an_answer_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="_Plain: form_kwargs returned None"):
        extra_keywords(_Plain, lambda: None, ValidationContext(object()))
