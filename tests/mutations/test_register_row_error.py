"""Tests for ``register_row_error``: a foreign refusal re-rooted under the row that raised it.

The stand-in below is the shape of the error class an adapter registers - the
one ``djangorestframework-services`` registers is DRF's ``ValidationError`` -
written from that class's source rather than imported, since nothing in this
suite may install DRF. What it reproduces, quirk for quirk:

- ``detail=None`` becomes the default message, a tuple becomes a list, and
  anything that is neither a list nor a dict is wrapped in a one-item list, so
  ``detail`` is only ever a list or a dict at the top.
- Below the top nothing is wrapped: a bare string inside a dict stays a bare
  message, and a dict's keys, ``int`` row indexes among them, are kept as they
  are.
- Every message is a ``str`` subclass carrying a ``code``, and one that already
  carries a code keeps it when the class is built again from a tree holding it.

So rebuilding the class from the re-rooted tree is lossless, which is the
contract ``register_row_error`` states.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.aupdate_from_input import aupdate_from_input
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.register_row_error import register_row_error
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.mutations.utils import ROW_ERROR_READERS
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.services.service_validation_error import ServiceValidationError
from tests.relations_app.models import Catalog, Item, Section


class _Message(str):
    """A message carrying the code of the mistake it names, as DRF's ``ErrorDetail``."""

    code: str | None

    def __new__(cls, text: str, code: str | None = None) -> _Message:
        message = super().__new__(cls, text)
        message.code = code
        return message


def _messages(data: Any, code: str) -> Any:
    """Every leaf of ``data`` as a ``_Message``, keeping a code it already has."""
    if isinstance(data, (list, tuple)):
        return [_messages(item, code) for item in data]
    if isinstance(data, dict):
        return {key: _messages(value, code) for key, value in data.items()}
    return _Message(str(data), getattr(data, "code", code))


class _ForeignRefusal(Exception):
    """The constructor of DRF's ``ValidationError``, which wraps only the top level."""

    def __init__(self, detail: Any = None, code: str | None = None) -> None:
        if detail is None:
            detail = "Invalid input."
        if code is None:
            code = "invalid"
        if isinstance(detail, tuple):
            detail = list(detail)
        elif not isinstance(detail, (dict, list)):
            detail = [detail]
        self.detail = _messages(detail, code)
        super().__init__(self.detail)


class _NarrowerRefusal(_ForeignRefusal):
    """A subclass, which the ``except`` at a row catches as its base."""


def _read_detail(exc: _ForeignRefusal) -> Any:
    return exc.detail


def _read_narrower_detail(exc: _NarrowerRefusal) -> Any:
    return {"narrower": ["Read as the narrower class."]}


def _codes(detail: Any) -> Any:
    """``detail`` with every message read as ``(message, code)``."""
    if isinstance(detail, dict):
        return {key: _codes(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_codes(item) for item in detail]
    return (str(detail), getattr(detail, "code", None))


@pytest.fixture(autouse=True)
def _restore_readers() -> Iterator[None]:
    """Leave the registrations as each test found them, so none leaks into the next."""
    before = dict(ROW_ERROR_READERS)
    yield
    ROW_ERROR_READERS.clear()
    ROW_ERROR_READERS.update(before)


@pytest.fixture
def registered() -> None:
    register_row_error(_ForeignRefusal, _read_detail)


def _refuses(error: Exception) -> Any:
    def service(**_: Any) -> None:
        raise error

    return service


def _arefuses(error: Exception) -> Any:
    async def service(**_: Any) -> None:
        raise error

    return service


_ROWS: dict[str, Any] = {"name": "c", "sections": [{"title": "ok"}, {"title": "bad"}]}


def _create_spec(error: Exception) -> dict[str, ChildSpec]:
    """Sections written by a service that refuses the row titled ``bad`` with ``error``."""

    def create(*, data: dict[str, Any]) -> Any:
        if data["title"] == "bad":
            raise error
        return Section.objects.create(**data)

    return {"sections": ChildSpec(model=Section, fk="catalog", create_service=create)}


def _acreate_spec(error: Exception) -> dict[str, ChildSpec]:
    """The async twin of ``_create_spec``."""

    async def create(*, data: dict[str, Any]) -> Any:
        if data["title"] == "bad":
            raise error
        return await Section.objects.acreate(**data)

    return {"sections": ChildSpec(model=Section, fk="catalog", create_service=create)}


@pytest.mark.django_db
class TestARowServiceRefusal:
    def test_a_create_lands_at_its_row_and_keeps_its_class(self, registered: None) -> None:
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(
                Catalog,
                _ROWS,
                relations=_create_spec(_ForeignRefusal({"title": ["No."]}, code="rude")),
            )
        assert type(excinfo.value) is _ForeignRefusal
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "rude")]}}}

    @pytest.mark.django_db(transaction=True)
    async def test_an_async_create_lands_at_its_row(self, registered: None) -> None:
        with pytest.raises(_ForeignRefusal) as excinfo:
            await acreate_from_input(
                Catalog,
                _ROWS,
                relations=_acreate_spec(_ForeignRefusal({"title": ["No."]})),
            )
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "invalid")]}}}

    def test_an_update_lands_at_its_row(self, registered: None) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="old")
        with pytest.raises(_ForeignRefusal) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"title": "new"}, {"pk": section.pk, "title": "bad"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        update_service=_refuses(_ForeignRefusal({"title": ["No."]})),
                    )
                },
            )
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "invalid")]}}}

    @pytest.mark.django_db(transaction=True)
    async def test_an_async_update_lands_at_its_row(self, registered: None) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="old")
        with pytest.raises(_ForeignRefusal) as excinfo:
            await aupdate_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "title": "bad"}]},
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        update_service=_arefuses(_ForeignRefusal({"title": ["No."]})),
                    )
                },
            )
        assert _codes(excinfo.value.detail) == {"sections": {0: {"title": [("No.", "invalid")]}}}

    def test_a_message_about_the_row_itself_lands_under_non_field_errors(
        self, registered: None
    ) -> None:
        # The constructor wraps a bare string in a list, and a list at a row is
        # the row's own complaint rather than a field of it.
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(Catalog, _ROWS, relations=_create_spec(_ForeignRefusal("Not today.")))
        assert _codes(excinfo.value.detail) == {
            "sections": {1: {"non_field_errors": [("Not today.", "invalid")]}}
        }

    def test_a_subclass_is_rebuilt_as_the_class_registered(self, registered: None) -> None:
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(
                Catalog,
                _ROWS,
                relations=_create_spec(_NarrowerRefusal({"title": ["No."]})),
            )
        assert type(excinfo.value) is _ForeignRefusal
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "invalid")]}}}

    def test_the_nearest_registered_class_answers(self, registered: None) -> None:
        # Registered after its base, and shadowing it for its own instances.
        register_row_error(_NarrowerRefusal, _read_narrower_detail)
        with pytest.raises(_NarrowerRefusal) as excinfo:
            create_from_input(
                Catalog, _ROWS, relations=_create_spec(_NarrowerRefusal({"title": ["No."]}))
            )
        assert _codes(excinfo.value.detail) == {
            "sections": {1: {"narrower": [("Read as the narrower class.", "invalid")]}}
        }

    def test_an_unregistered_class_passes_through_untouched(self) -> None:
        refusal = _ForeignRefusal({"title": ["No."]})
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(Catalog, _ROWS, relations=_create_spec(refusal))
        assert excinfo.value is refusal


def _items_refused_by(service: Any) -> dict[str, ChildSpec]:
    """Sections written by the helper, whose items a service refuses."""
    return {
        "sections": ChildSpec(
            model=Section,
            fk="catalog",
            relations={"items": ChildSpec(model=Item, fk="section", create_service=service)},
        )
    }


@pytest.mark.django_db
class TestAGrandchildRefusal:
    """The helper path re-roots a registered refusal too, so both addresses are named."""

    def test_a_create_carries_both_rows(self, registered: None) -> None:
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "s", "items": [{"label": "i"}]}]},
                relations=_items_refused_by(_refuses(_ForeignRefusal({"label": ["No."]}))),
            )
        assert type(excinfo.value) is _ForeignRefusal
        assert _codes(excinfo.value.detail) == {
            "sections": {0: {"items": {0: {"label": [("No.", "invalid")]}}}}
        }

    @pytest.mark.django_db(transaction=True)
    async def test_an_async_create_carries_both_rows(self, registered: None) -> None:
        with pytest.raises(_ForeignRefusal) as excinfo:
            await acreate_from_input(
                Catalog,
                {"name": "c", "sections": [{"title": "s", "items": [{"label": "i"}]}]},
                relations=_items_refused_by(_arefuses(_ForeignRefusal({"label": ["No."]}))),
            )
        assert _codes(excinfo.value.detail) == {
            "sections": {0: {"items": {0: {"label": [("No.", "invalid")]}}}}
        }

    def test_an_update_carries_both_rows(self, registered: None) -> None:
        catalog = Catalog.objects.create(name="c")
        section = Section.objects.create(catalog=catalog, title="s")
        with pytest.raises(_ForeignRefusal) as excinfo:
            update_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "items": [{"label": "i"}]}]},
                relations=_items_refused_by(_refuses(_ForeignRefusal({"label": ["No."]}))),
            )
        assert _codes(excinfo.value.detail) == {
            "sections": {0: {"items": {0: {"label": [("No.", "invalid")]}}}}
        }

    @pytest.mark.django_db(transaction=True)
    async def test_an_async_update_carries_both_rows(self, registered: None) -> None:
        catalog = await Catalog.objects.acreate(name="c")
        section = await Section.objects.acreate(catalog=catalog, title="s")
        with pytest.raises(_ForeignRefusal) as excinfo:
            await aupdate_from_input(
                catalog,
                {"sections": [{"pk": section.pk, "items": [{"label": "i"}]}]},
                relations=_items_refused_by(_arefuses(_ForeignRefusal({"label": ["No."]}))),
            )
        assert _codes(excinfo.value.detail) == {
            "sections": {0: {"items": {0: {"label": [("No.", "invalid")]}}}}
        }


@pytest.mark.django_db
class TestRegistering:
    def test_the_same_pair_twice_is_one_registration(self) -> None:
        register_row_error(_ForeignRefusal, _read_detail)
        register_row_error(_ForeignRefusal, _read_detail)
        # Registered once, so the row is addressed once rather than twice.
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(
                Catalog, _ROWS, relations=_create_spec(_ForeignRefusal({"title": ["No."]}))
            )
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "invalid")]}}}

    def test_a_second_reader_for_one_class_is_refused(self, registered: None) -> None:
        with pytest.raises(ImproperlyConfigured, match="_ForeignRefusal is already registered"):
            register_row_error(_ForeignRefusal, lambda exc: exc.detail)

    def test_the_reader_registered_first_still_answers_after_a_refused_second(
        self, registered: None
    ) -> None:
        with pytest.raises(ImproperlyConfigured):
            register_row_error(_ForeignRefusal, lambda exc: {"other": ["Other."]})
        with pytest.raises(_ForeignRefusal) as excinfo:
            create_from_input(
                Catalog, _ROWS, relations=_create_spec(_ForeignRefusal({"title": ["No."]}))
            )
        assert _codes(excinfo.value.detail) == {"sections": {1: {"title": [("No.", "invalid")]}}}

    @pytest.mark.parametrize("not_an_error", [object, "ValidationError", int])
    def test_what_is_not_an_exception_class_is_refused(self, not_an_error: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match="is not an exception class"):
            register_row_error(not_an_error, _read_detail)

    @pytest.mark.parametrize(
        "handled",
        [ServiceValidationError, InvalidArguments, ValueError, TypeError, ValidationError],
    )
    def test_a_class_the_kernel_already_reads_is_refused(self, handled: type[Exception]) -> None:
        # Each of the five, so deleting any one from the guard fails a case.
        narrower = type("Narrower", (handled,), {})
        with pytest.raises(ImproperlyConfigured, match=f"Narrower overlaps {handled.__name__}, "):
            register_row_error(narrower, _read_detail)

    def test_a_class_wider_than_one_the_kernel_reads_is_refused(self) -> None:
        # ``Exception`` would catch every caller's own bug at a row as a refusal.
        with pytest.raises(
            ImproperlyConfigured,
            match="Exception overlaps ServiceValidationError, InvalidArguments, ValueError, "
            "TypeError, ValidationError, ",
        ):
            register_row_error(Exception, _read_detail)

    def test_a_class_beside_the_kernels_is_accepted(self) -> None:
        # Overlapping none of the five, in either direction: what tells the
        # guard's two directions apart from a guard refusing every builtin.
        register_row_error(LookupError, _read_detail)
        assert ROW_ERROR_READERS[LookupError] is _read_detail
