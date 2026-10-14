"""``NoInput``: a name for an empty ``InputT``, which carries nothing at run time."""

from __future__ import annotations

from django_service_specs.services.delete_service import DeleteService
from django_service_specs.types.no_input import NoInput


def test_it_declares_nothing_of_its_own() -> None:
    assert [name for name in vars(NoInput) if not name.startswith("__")] == []


def test_it_binds_a_protocol_s_input_type() -> None:
    bound = DeleteService[NoInput, object, None]

    assert bound.__args__ == (NoInput, object, type(None))
