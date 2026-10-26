"""Dispatching: results, not-found, grants, admitting, binding outside dispatch, seeds, progress."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    DataclassPresenter,
    DataclassValidator,
    DispatchResult,
    Grant,
    Parameter,
    Parameters,
    PermissionCheck,
    PoolSeeds,
    ProgressReporter,
    SelectorKind,
    SelectorSpec,
    ServerArguments,
    ServiceSpec,
    apply_server_arguments,
    authorize,
    bind_arguments,
    check_call,
    check_server_arguments,
    dispatch,
    present,
    resolve_target,
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


# --8<-- [start:arguments_channel]
class NotLocked(PermissionCheck):
    message = "That note is locked."

    def __init__(self, *locked: int) -> None:
        self.locked = frozenset(locked)

    # Declaring ``arguments`` asks for the call's shape-checked arguments; a
    # check that does not declare it is asked as it always was.
    def has_permission(
        self, principal: Any, spec: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        if arguments is None:
            # A transport called ``authorize()`` without ``arguments=``: there
            # is no pk to judge, so this check refuses rather than allowing.
            return False
        return arguments.get("pk") not in self.locked


lockable_note_spec = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, user, pk: Note.objects.filter(owner=user, pk=pk),
    permissions=[IsSignedIn(), NotLocked(7)],
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


# --8<-- [end:arguments_channel]


# --8<-- [start:overlays]
def stamp(*, title: str, source: str, channel: str) -> str:
    return f"{title} via {source} on {channel}"


stamp_spec = ServiceSpec(
    service=stamp,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(Rename),
    kwargs=lambda: {"channel": "api"},  # the spec's own provider
)


def stamp_from_a_view(user: Any, arguments: dict[str, Any]) -> DispatchResult:
    # What the view's per-request hook resolved, beneath the spec's provider:
    # the provider's ``channel`` wins, and the hook's ``source`` fills the gap.
    # A value for the Validator goes into ``arguments``, where the permission
    # checks read it too.
    return dispatch(
        stamp_spec,
        principal=user,
        arguments=arguments,
        extra_kwargs={"source": "web", "channel": "web"},
    )


# --8<-- [end:overlays]


# --8<-- [start:bind]
def bind_rename(user: Any, note: Note, arguments: dict[str, Any]) -> dict[str, Any]:
    # A transport that binds input itself authorizes and resolves first, then
    # runs the same shape check and Validator dispatch would have run.
    return bind_arguments(rename_note_spec, arguments, principal=user, target=note)


# --8<-- [end:bind]


# --8<-- [start:check_call]
def enqueue_rename(user: Any, arguments: dict[str, Any], queue: list[Any]) -> None:
    # Refused here, before anything is queued, by the steps dispatch runs
    # first; the job carries what was sent, and the worker dispatches it.
    check_call(rename_note_spec, principal=user, arguments=arguments)
    queue.append((user.pk, arguments))


# --8<-- [end:check_call]


# --8<-- [start:server_arguments]
def notes_by(*, author_pk: int, search: str = "", ordering: str = "title") -> QuerySet[Note]:
    return Note.objects.filter(owner_id=author_pk, title__icontains=search).order_by(ordering)


notes_by_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=notes_by,
    permissions=[IsSignedIn()],
    reads=Parameters.of(
        Parameter("author_pk", "integer", required=True),
        Parameter("search", "string"),
        Parameter("ordering", "string", choices=["title", "-title"], default="title"),
    ),
)


def notes_tool(user: Any) -> Callable[[Mapping[str, Any]], DispatchResult]:
    # The signed-in user's own notes, in the server's order: the caller is
    # offered neither name, and whatever it sends for either is dropped.
    server = ServerArguments(values={"author_pk": user.pk}, withheld=frozenset({"ordering"}))
    # Once, where the tool is built, so a binding that cannot work fails here.
    check_server_arguments(notes_by_spec, server)

    def call(arguments: Mapping[str, Any]) -> DispatchResult:
        applied = apply_server_arguments(notes_by_spec, arguments, server)
        return dispatch(notes_by_spec, principal=user, arguments=applied)

    return call


def offered(schema: Mapping[str, Any], server: ServerArguments) -> list[str]:
    # What a transport's own schema builder lists, less the server's names.
    return sorted(set(schema["properties"]) - server.names())


# --8<-- [end:server_arguments]


# --8<-- [start:admit]
class InClub(PermissionCheck):
    """Admits a member of the club the route names, read from a seed."""

    message = "Members of this club only."

    def has_permission(self, principal: Any, spec: Any, *, club: str) -> bool:
        return principal.groups.filter(name=club).exists()


def post_to_club(*, user: Any, title: str, club: str) -> Note:
    return Note.objects.create(owner=user, title=f"{club}: {title}")


club_note_spec = ServiceSpec(
    service=post_to_club,
    permissions=[InClub()],
    validator=DataclassValidator(Rename),
)


def club_seeds(club: str) -> PoolSeeds:
    # Built per request, from what the route captured.
    return DEFAULT_POOL_SEEDS.extend(club=lambda: club)


def club_note_page(user: Any, club: str, title: str | None = None) -> Any:
    pool_seeds = club_seeds(club)
    # Before the form: a principal the class-level check refuses never sees
    # it. NotPermitted for anyone outside the club.
    grant = authorize(club_note_spec, user, pool_seeds=pool_seeds)
    if title is None:
        return "the form"  # the GET
    return dispatch(
        club_note_spec,
        principal=user,
        arguments={"title": title},
        pool_seeds=pool_seeds,
        grant=grant,
    )


# --8<-- [end:admit]


# --8<-- [start:resolve_target]
def rename_page(user: Any, pk: int, title: str | None = None) -> Any:
    found = resolve_target(rename_note_spec, principal=user, arguments={"pk": pk})
    if isinstance(found, DispatchResult):
        return None  # not found: the answer dispatch would give
    note, grant = found  # NotPermitted was raised already for anyone else
    if title is None:
        return note  # the GET: the row the form will act on
    # The POST acts on the row already found and checked: no second lookup,
    # and the grant says has_object_permission was asked.
    result = dispatch(
        rename_note_spec,
        principal=user,
        arguments={"pk": pk, "title": title},
        target=note,
        grant=grant,
    )
    return present(rename_note_spec, result)


# --8<-- [end:resolve_target]


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


# --8<-- [start:reflected_seed]
def notes_signed_by(*, user: Any, signature: str) -> QuerySet[Note]:
    return Note.objects.filter(owner=user, title__endswith=f", by {signature}")


# The read is marked reflected, so the registered ``signature`` seed fills it
# on every call: it is no argument of the call, and a caller naming it is
# refused as an unknown argument.
signed_notes_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=notes_signed_by,
    permissions=[IsSignedIn()],
    reads=Parameters.of(Parameter("signature", "string", required=True, reflected=True)),
)


def my_signed_notes(user: Any) -> DispatchResult:
    return dispatch(signed_notes_spec, principal=user, arguments={}, pool_seeds=seeds)


# --8<-- [end:reflected_seed]


# --8<-- [start:seed_named_field]
@dataclass
class Countersign:
    title: str
    signature: str  # the caller's own: validated into ``data``, never the pool


def countersign(*, user: Any, data: Countersign, signature: str) -> Note:
    # ``signature`` is the seed's, whatever the caller sent under that name.
    return Note.objects.create(
        owner=user, title=f"{data.title}, by {data.signature} for {signature}"
    )


countersign_spec = ServiceSpec(
    service=countersign,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(Countersign),
)


def create_countersigned_note(user: Any, title: str, signature: str) -> DispatchResult:
    return dispatch(
        countersign_spec,
        principal=user,
        arguments={"title": title, "signature": signature},
        pool_seeds=seeds,
    )


# --8<-- [end:seed_named_field]


# --8<-- [start:progress]
def retitle_all(*, user: Any, title: str, progress: ProgressReporter) -> int:
    notes = list(Note.objects.filter(owner=user).order_by("pk"))
    for done, note in enumerate(notes, start=1):
        note.title = title
        note.save(update_fields=["title"])
        progress(done, total=len(notes), message="retitling notes")
    return len(notes)


retitle_all_spec = ServiceSpec(
    service=retitle_all,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(Rename),
)


def retitle_all_reporting(user: Any, title: str, report: ProgressReporter) -> int:
    # The transport's own reporter; with none, the service gets null_progress.
    result = dispatch(retitle_all_spec, principal=user, arguments={"title": title}, progress=report)
    return result.value


# --8<-- [end:progress]


# --8<-- [start:call_context]
class FromBackOffice(PermissionCheck):
    message = "Only the back office may archive a note."

    # A keyword named ``call_context`` asks for the call's context, as
    # ``arguments`` asks for its arguments.
    def has_permission(self, principal: Any, spec: Any, *, call_context: dict[str, Any]) -> bool:
        return call_context.get("client") == "back-office"


def archive_note(*, user: Any, pk: int, call_context: dict[str, Any]) -> Note:
    note = Note.objects.get(owner=user, pk=pk)
    note.archived = True
    note.save(update_fields=["archived"])
    # Left for whatever stage of the request comes next.
    call_context.setdefault("archived", []).append(note.pk)
    return note


archive_note_spec = ServiceSpec(
    service=archive_note,
    permissions=[IsSignedIn(), FromBackOffice()],
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def archive_from_back_office(user: Any, pk: int) -> dict[str, Any]:
    # One dict per request, created by the transport and filled as it likes.
    context: dict[str, Any] = {"client": "back-office"}
    dispatch(archive_note_spec, principal=user, arguments={"pk": pk}, call_context=context)
    return context


# --8<-- [end:call_context]
