"""Dispatching: results, not-found, grants, binding outside dispatch, and pool seeds."""

from __future__ import annotations

from typing import Any

from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    DataclassPresenter,
    DataclassValidator,
    DispatchResult,
    Grant,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    bind_arguments,
    dispatch,
    present,
)
from docs.examples.declaring import IsSignedIn, NoteRow, list_notes_spec
from docs.examples.quickstart import Rename, rename_note_spec
from tests.dispatch_app.models import Note


# --8<-- [start:list]
def list_notes(user: Any) -> list[dict[str, Any]]:
    result = dispatch(list_notes_spec, principal=user, arguments={"ordering": "-title"})
    # result.kind is "list", and result.value the shaped queryset, not yet read.
    return present(list_notes_spec, result)  # one dict per row, in order


# --8<-- [end:list]


# --8<-- [start:retrieve]
note_spec = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, user, pk: Note.objects.filter(owner=user, pk=pk),
    permissions=[IsSignedIn()],
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    presenter=DataclassPresenter(NoteRow),
)


def show_note(user: Any, pk: int) -> tuple[int, Any]:
    result = dispatch(note_spec, principal=user, arguments={"pk": pk})
    if result.kind == "not_found":
        return 404, {"detail": "Not found."}
    return 200, present(note_spec, result)


# --8<-- [end:retrieve]


# --8<-- [start:grant]
def rename_from_a_view(user: Any, arguments: dict[str, Any]) -> DispatchResult:
    # The view's own permission machinery has already run for this user and
    # this operation, so it says so rather than paying for the check twice.
    grant = Grant(spec=rename_note_spec, principal=user)
    return dispatch(rename_note_spec, principal=user, arguments=arguments, grant=grant)


# --8<-- [end:grant]


# --8<-- [start:bind]
def bind_rename(user: Any, note: Note, arguments: dict[str, Any]) -> dict[str, Any]:
    # A transport that binds input itself authorizes and resolves first, then
    # runs the same shape check and Validator dispatch would have run.
    return bind_arguments(rename_note_spec, arguments, principal=user, target=note)


# --8<-- [end:bind]


# --8<-- [start:seeds]
seeds = DEFAULT_POOL_SEEDS.extend(signature=lambda *, user: user.get_username())


def sign_note(*, user: Any, title: str, signature: str) -> Note:
    return Note.objects.create(owner=user, title=f"{title}, by {signature}")


sign_note_spec = ServiceSpec(
    service=sign_note,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(Rename),
)


def create_signed_note(user: Any, title: str) -> DispatchResult:
    return dispatch(sign_note_spec, principal=user, arguments={"title": title}, pool_seeds=seeds)


# --8<-- [end:seeds]
