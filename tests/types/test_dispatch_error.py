from __future__ import annotations

from django_service_specs.types.dispatch_error import DispatchError


def test_message_defaults_and_is_the_exception_text() -> None:
    error = DispatchError()
    assert error.message == DispatchError.default_message
    assert str(error) == DispatchError.default_message


def test_an_explicit_message_wins_even_when_empty() -> None:
    # ``""`` is a message someone chose; only ``None`` means "use the default".
    assert DispatchError("stop").message == "stop"
    assert DispatchError("").message == ""
