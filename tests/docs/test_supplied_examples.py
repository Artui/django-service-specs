from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from docs.examples import supplied
from tests.dispatch_app.models import Note

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.mark.django_db
def test_a_filter_left_out_filters_nothing(ada: Any) -> None:
    plan = Note.objects.create(owner=ada, title="Plan")
    old = Note.objects.create(owner=ada, title="Old", archived=True)

    everything = supplied.matching_notes(user=ada, query=supplied.NoteQuery())
    archived = supplied.matching_notes(user=ada, query=supplied.NoteQuery(archived=True))

    assert list(everything) == [plan, old]
    assert list(archived) == [old]


def test_the_heading_reads_the_title_only_when_it_was_sent() -> None:
    assert supplied.heading(supplied.NoteQuery(title="plan")) == "PLAN"
    assert supplied.heading(supplied.NoteQuery()) == "All notes"


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
            str(ROOT / "docs" / "examples" / "supplied.py"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
