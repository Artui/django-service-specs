"""The typing section's example, run, and checked by the type checker it names."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from django_service_specs import dispatch
from docs.examples import typing_services
from tests.dispatch_app.models import Note

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.mark.django_db
def test_the_typed_services_dispatch_as_any_other(ada: Any) -> None:
    created = dispatch(typing_services.create_note_spec, principal=ada, arguments={"title": "Plan"})
    assert created.value.title == "Plan"

    dispatch(typing_services.delete_note_spec, principal=ada, arguments={"pk": created.value.pk})

    assert not Note.objects.exists()


def test_the_example_conforms_under_ty() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ty",
            "check",
            "--python",
            sys.prefix,
            "--output-format",
            "concise",
            str(ROOT / "docs" / "examples" / "typing_services.py"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
