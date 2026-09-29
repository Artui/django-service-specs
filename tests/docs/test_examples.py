"""The documentation's examples, run.

Every page includes its code from ``docs/examples/`` rather than carrying a
copy, and these tests run that code, so a page cannot describe behaviour the
package does not have. Where a page states an outcome - a refusal's tree, what
an adapter declares, which rows a nested write changed - the assertion here is
that statement.

``docs/`` and ``docs/examples/`` are packages so the examples import by their
path from the repository root, which pytest already puts on ``sys.path`` for
the ``tests`` package; no path is patched here.
"""

from __future__ import annotations

import importlib
import json
import pickle
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

import django_service_specs
from django_service_specs import (
    UNSET,
    ChildCollectionChange,
    DataclassValidator,
    DispatchError,
    FieldAudience,
    Grant,
    InvalidArguments,
    NotPermitted,
    Parameter,
    Parameters,
    PrincipalUnavailable,
    SelectorKind,
    SelectorSpec,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceSpec,
    ServiceValidationError,
    SpecRegistry,
    ValidationContext,
    coerce_flat,
    dispatch,
    error_response,
    present,
    update_from_input,
)
from docs.examples import (
    arguments,
    async_dispatch,
    declaring,
    deleting,
    dispatching,
    quickstart,
    registry,
    relations,
    transport,
)
from tests.adapter_app.models import Author, Book
from tests.dispatch_app.models import Note
from tests.test_init import OPTIONAL_LIBRARY_ADAPTERS

ROOT = Path(__file__).resolve().parents[2]


def make_user(username: str, **extra: Any) -> Any:
    return get_user_model().objects.create_user(username=username, **extra)


def section(path: Path, name: str) -> str:
    """The text between a snippet section's markers, as the docs build includes it."""
    text = path.read_text()
    start = text.index(f"# --8<-- [start:{name}]\n") + len(f"# --8<-- [start:{name}]\n")
    return text[start : text.index(f"# --8<-- [end:{name}]")]


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def bob() -> Any:
    return make_user("bob")


@pytest.mark.django_db
class TestQuickstart:
    def test_the_owner_renames_their_note(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        assert quickstart.rename(ada, {"pk": note.pk, "title": "Final"}) == {
            "id": note.pk,
            "title": "Final",
        }
        note.refresh_from_db()
        assert note.title == "Final"

    def test_another_user_is_refused_on_the_row(self, ada: Any, bob: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        with pytest.raises(NotPermitted) as refused:
            quickstart.rename(bob, {"pk": note.pk, "title": "Mine now"})
        assert refused.value.message == "Only the note's owner may rename it."
        note.refresh_from_db()
        assert note.title == "Draft"

    def test_a_missing_note_is_reported_rather_than_raised(self, ada: Any) -> None:
        assert quickstart.rename(ada, {"pk": 404, "title": "Final"}) is None

    def test_a_refused_principal_learns_nothing_about_which_rows_exist(self) -> None:
        # Class-level authorization runs before resolution, so the missing row
        # and the present one are refused alike.
        with pytest.raises(NotPermitted):
            quickstart.rename(AnonymousUser(), {"pk": 404, "title": "Final"})

    def test_an_undeclared_argument_is_refused_before_anything_runs(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        with pytest.raises(InvalidArguments) as refused:
            quickstart.rename(ada, {"pk": note.pk, "title": "Final", "colour": "red"})
        assert refused.value.detail == {"colour": ["Unknown argument."]}

    def test_the_readme_carries_this_example_verbatim(self) -> None:
        readme = (ROOT / "README.md").read_text()
        after = readme[readme.index("## Quickstart") :]
        block = re.search(r"```python\n(.*?)```", after, re.DOTALL)
        assert block is not None
        example = section(ROOT / "docs" / "examples" / "quickstart.py", "quickstart")
        # One line differs, on purpose: the example imports its model from the
        # suite's own app, and the README names an app a reader would have.
        # Swapping exactly that line keeps every other byte checked.
        run_from = "from tests.dispatch_app.models import Note"
        shown_as = "from notes.models import Note"
        assert example.count(run_from) == 1
        assert block.group(1).strip() == example.replace(run_from, shown_as).strip()


class TestDeclaring:
    def test_a_read_takes_exactly_its_reads(self) -> None:
        params = declaring.list_notes_spec.parameters()
        assert [p.name for p in params] == ["search", "ordering"]
        ordering = params.get("ordering")
        assert ordering is not None
        assert ordering.choices == ("title", "-title")
        assert ordering.default == "title"

    def test_the_presenter_declares_a_handle_and_a_label(self) -> None:
        output = declaring.list_notes_spec.output()
        assert output is not None
        assert [(f.name, f.type, f.marking.audience) for f in output if f.marking] == [
            ("id", "integer", FieldAudience.HANDLE),
            ("title", "string", FieldAudience.LABEL),
        ]

    def test_the_dataclass_validator_declares_what_the_page_says(self) -> None:
        params = DataclassValidator(declaring.AuthorIn).parameters()
        name, books = params.get("name"), params.get("books")
        assert name is not None and name.required and name.type == "string"
        assert books is not None and books.type == "array" and not books.required
        assert isinstance(books.items, Parameters)
        rows = {p.name: p for p in books.items}
        assert list(rows) == ["title", "price", "status", "published_on", "pk"]
        assert (rows["price"].type, rows["price"].format, rows["price"].required) == (
            "string",
            "decimal",
            True,
        )
        assert rows["status"].choices == ("draft", "published")
        assert rows["status"].default == "draft"
        assert (rows["published_on"].format, rows["published_on"].nullable) == ("date", True)
        assert (rows["pk"].type, rows["pk"].nullable, rows["pk"].required) == (
            "integer",
            True,
            False,
        )

    def test_a_patch_leaves_every_unsent_field_unset(self) -> None:
        validator = DataclassValidator(declaring.AuthorPatch)
        assert [p.required for p in validator.parameters()] == [False, False]
        assert validator.validate({}, ValidationContext(None)) == {"name": UNSET, "books": UNSET}


@pytest.mark.django_db
class TestDispatching:
    def test_a_list_is_presented_row_by_row(self, ada: Any, bob: Any) -> None:
        first = Note.objects.create(owner=ada, title="Apples")
        second = Note.objects.create(owner=ada, title="Pears")
        Note.objects.create(owner=bob, title="Plums")
        assert dispatching.list_notes(ada) == [
            {"id": second.pk, "title": "Pears"},
            {"id": first.pk, "title": "Apples"},
        ]

    def test_a_row_outside_the_selector_is_not_found(self, ada: Any, bob: Any) -> None:
        mine = Note.objects.create(owner=ada, title="Mine")
        theirs = Note.objects.create(owner=bob, title="Theirs")
        assert dispatching.show_note(ada, mine.pk) == (200, {"id": mine.pk, "title": "Mine"})
        assert dispatching.show_note(ada, theirs.pk) == (404, {"detail": "Not found."})

    def test_present_refuses_a_not_found_result(self, ada: Any) -> None:
        result = dispatch(dispatching.note_spec, principal=ada, arguments={"pk": 404})
        assert result.kind == "not_found"
        with pytest.raises(ValueError, match="nothing to present"):
            present(dispatching.note_spec, result)

    def test_a_grant_skips_the_class_level_check_and_not_the_row(self, ada: Any, bob: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        result = dispatching.rename_from_a_view(ada, {"pk": note.pk, "title": "Final"})
        assert result.kind == "instance" and result.value.title == "Final"
        # ``target_checked`` was not claimed, so the object-level check still runs.
        with pytest.raises(NotPermitted):
            dispatching.rename_from_a_view(bob, {"pk": note.pk, "title": "Mine now"})

    def test_a_grant_covers_one_principal_and_never_crosses_a_queue(
        self, ada: Any, bob: Any
    ) -> None:
        grant = Grant(spec=quickstart.rename_note_spec, principal=ada)
        with pytest.raises(NotPermitted, match="does not cover"):
            dispatch(
                quickstart.rename_note_spec,
                principal=bob,
                arguments={"pk": 1, "title": "x"},
                grant=grant,
            )
        with pytest.raises(TypeError, match="cannot be serialized"):
            pickle.dumps(grant)

    def test_binding_outside_dispatch_returns_only_the_validators_values(self, ada: Any) -> None:
        note = Note.objects.create(owner=ada, title="Draft")
        bound = dispatching.bind_rename(ada, note, {"pk": note.pk, "title": "Final"})
        assert bound == {"title": "Final"}
        with pytest.raises(InvalidArguments) as refused:
            dispatching.bind_rename(ada, note, {"pk": note.pk})
        assert refused.value.detail == {"title": ["This field is required."]}

    def test_a_seed_reaches_the_service_and_no_caller_can_supply_it(self, ada: Any) -> None:
        result = dispatching.create_signed_note(ada, "Hello")
        assert result.value.title == "Hello, by ada"
        with pytest.raises(InvalidArguments) as refused:
            dispatch(
                dispatching.sign_note_spec,
                principal=ada,
                arguments={"title": "Hello", "signature": "someone else"},
                pool_seeds=dispatching.seeds,
            )
        assert refused.value.detail == {"signature": ["Unknown argument."]}

    def test_a_spec_declaring_a_seeds_name_is_refused(self, ada: Any) -> None:
        clashing = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda *, signature: Note.objects.none(),
            permissions=[declaring.IsSignedIn()],
            reads=Parameters.of(Parameter("signature", "string")),
        )
        with pytest.raises(ImproperlyConfigured, match="registered pool seed"):
            dispatch(clashing, principal=ada, arguments={}, pool_seeds=dispatching.seeds)

    def test_a_dispatchers_own_name_cannot_be_registered(self) -> None:
        with pytest.raises(ValueError, match="reserved pool seed"):
            dispatching.seeds.extend(user=lambda: None)


@pytest.mark.django_db(transaction=True)
class TestAsyncDispatch:
    def test_the_sync_entry_point_drives_an_async_service(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        result = dispatch(
            async_dispatch.arename_note_spec,
            principal=ada,
            arguments={"pk": note.pk, "title": "Final"},
        )
        assert present(async_dispatch.arename_note_spec, result) == {
            "id": note.pk,
            "title": "Final",
        }
        note.refresh_from_db()
        assert note.title == "Final"

    async def test_a_worker_dispatches_by_identifier(self) -> None:
        ada = await get_user_model().objects.acreate(username="ada")
        note = await Note.objects.acreate(owner=ada, title="Draft")
        renamed = await async_dispatch.rename_from_a_worker(
            ada.pk, {"pk": note.pk, "title": "Final"}
        )
        assert renamed == {"id": note.pk, "title": "Final"}
        await note.arefresh_from_db()
        assert note.title == "Final"

    async def test_a_missing_or_deactivated_principal_is_refused(self) -> None:
        gone = await get_user_model().objects.acreate(username="gone", is_active=False)
        for identifier in (gone.pk, 404, "not a key"):
            with pytest.raises(PrincipalUnavailable):
                await async_dispatch.rename_from_a_worker(identifier, {"pk": 1, "title": "x"})

    async def test_the_object_level_check_runs_on_the_async_path(self) -> None:
        ada = await get_user_model().objects.acreate(username="ada")
        bob = await get_user_model().objects.acreate(username="bob")
        note = await Note.objects.acreate(owner=ada, title="Draft")
        with pytest.raises(NotPermitted):
            await async_dispatch.rename_from_a_worker(bob.pk, {"pk": note.pk, "title": "x"})


class TestArguments:
    def test_every_problem_comes_back_in_one_tree(self) -> None:
        assert arguments.refusal(arguments.ARGUMENTS) == arguments.REFUSED

    def test_the_tree_serializes_with_its_row_keys_as_strings(self) -> None:
        assert json.loads(json.dumps(arguments.REFUSED))["books"].keys() == {"1", "2"}

    def test_ignore_drops_an_undeclared_key_at_every_level(self) -> None:
        assert arguments.lenient(arguments.SENT) == arguments.KEPT

    def test_a_flat_transport_reads_strings_as_typed_json(self) -> None:
        assert arguments.from_argv(arguments.ARGV) == arguments.TYPED

    def test_a_boolean_has_four_spellings(self) -> None:
        with pytest.raises(InvalidArguments) as refused:
            arguments.from_argv({"published": "yes"})
        assert refused.value.detail == {"published": ["Enter true, false, 1 or 0."]}

    def test_a_nested_parameter_has_no_flat_spelling(self) -> None:
        with pytest.raises(InvalidArguments) as refused:
            coerce_flat(arguments.AUTHOR, {"books": "The Dispossessed"})
        assert refused.value.detail == {
            "books": ["This argument has nested parameters, which a flat transport cannot send."]
        }

    def test_neither_error_family_subclasses_the_other(self) -> None:
        assert not issubclass(DispatchError, ServiceError)
        assert not issubclass(ServiceError, DispatchError)
        for refusal in (InvalidArguments, NotPermitted, PrincipalUnavailable):
            assert issubclass(refusal, DispatchError)
            assert not issubclass(refusal, ServiceError)


def _conflicting(*, title: str) -> None:
    raise ServiceConflict(f"{title!r} is taken.")


def _invalid(*, title: str) -> None:
    raise ServiceValidationError({"title": ["Too dull."]})


def _invalid_as_a_whole(*, title: str) -> None:
    raise ServiceValidationError("Pick another day.")


def _missing(*, title: str) -> None:
    raise ServiceNotFound("No such shelf.")


def _refusing(*, title: str) -> None:
    raise ServiceError("Not today.")


def _raising(exc: Exception) -> Any:
    def service(*, title: str) -> None:
        raise exc

    return service


@pytest.mark.django_db
class TestTransport:
    def test_each_outcome_has_its_own_answer(self, ada: Any, bob: Any) -> None:
        spec = quickstart.rename_note_spec
        note = Note.objects.create(owner=ada, title="Draft")
        answer = transport.answer
        assert answer(spec, ada, {"pk": note.pk, "title": "Final"}) == (
            200,
            {"id": note.pk, "title": "Final"},
        )
        assert answer(spec, ada, {"pk": note.pk}) == (400, {"title": ["This field is required."]})
        assert answer(spec, bob, {"pk": note.pk, "title": "x"}) == (
            403,
            {"detail": "Only the note's owner may rename it."},
        )
        assert answer(spec, ada, {"pk": 404, "title": "x"}) == (404, {"detail": "Not found."})

    @pytest.mark.parametrize(
        ("service", "expected"),
        [
            (_invalid, (400, {"title": ["Too dull."]})),
            (_invalid_as_a_whole, (400, {"non_field_errors": ["Pick another day."]})),
            (_missing, (404, {"detail": "No such shelf."})),
            (_conflicting, (409, {"detail": "'Final' is taken."})),
            (_refusing, (422, {"detail": "Not today."})),
        ],
    )
    def test_the_operations_own_refusals(self, ada: Any, service: Any, expected: Any) -> None:
        spec = ServiceSpec(
            service=service,
            permissions=[declaring.IsSignedIn()],
            validator=DataclassValidator(quickstart.Rename),
        )
        assert transport.answer(spec, ada, {"title": "Final"}) == expected

    @pytest.mark.parametrize(
        "refusal",
        [
            InvalidArguments({"title": ["Too dull."]}),
            NotPermitted("No."),
            PrincipalUnavailable(),
            ServiceValidationError({"title": ["Too dull."]}),
            ServiceValidationError("Pick another day."),
            ServiceValidationError(["One.", "Two."]),
            ServiceNotFound("No such shelf."),
            ServiceConflict("Taken."),
            ServiceError("Not today."),
        ],
        ids=lambda refusal: f"{type(refusal).__name__}-{refusal}",
    )
    def test_the_ladder_is_the_one_error_response_ships(self, ada: Any, refusal: Any) -> None:
        # The page says so, and the arguments page's reader copies this
        # ladder into a transport: a status that drifted from the shipped one
        # would teach a client two answers to one refusal.
        spec = ServiceSpec(
            service=_raising(refusal),
            permissions=[declaring.IsSignedIn()],
            validator=DataclassValidator(quickstart.Rename),
        )
        shipped = error_response(refusal)
        assert transport.answer(spec, ada, {"title": "Final"}) == (
            shipped.status_code,
            json.loads(shipped.content),
        )


@pytest.mark.django_db
class TestRelations:
    BOOKS = [{"title": "The Dispossessed", "price": "9.99"}, {"title": "Lathe", "price": 12.5}]

    def _create(self, user: Any) -> Any:
        return dispatch(
            relations.create_author_spec,
            principal=user,
            arguments={"name": "Ursula", "books": self.BOOKS},
        )

    def test_a_create_writes_the_author_and_its_books(self, ada: Any) -> None:
        result = self._create(ada)
        author = result.value
        first, second = author.books.all()
        assert result.service_result.get_child_change("books") == ChildCollectionChange(
            relation="books", created=(first.pk, second.pk)
        )
        assert present(relations.create_author_spec, result) == {
            "id": author.pk,
            "name": "Ursula",
            "books": [
                {"id": first.pk, "title": "The Dispossessed", "price": "9.99", "status": "draft"},
                {"id": second.pk, "title": "Lathe", "price": "12.50", "status": "draft"},
            ],
        }

    def test_an_update_reconciles_the_books_by_primary_key(self, ada: Any) -> None:
        author = self._create(ada).value
        kept, dropped = author.books.all()
        result = dispatch(
            relations.update_author_spec,
            principal=ada,
            arguments={
                "pk": author.pk,
                "books": [
                    {"pk": kept.pk, "title": "The Dispossessed", "price": "10.99"},
                    {"title": "Always Coming Home", "price": "8"},
                ],
            },
        )
        added = Book.objects.get(title="Always Coming Home")
        assert result.service_result.get_child_change("books") == ChildCollectionChange(
            relation="books", created=(added.pk,), updated=(kept.pk,), deleted=(dropped.pk,)
        )
        assert not Book.objects.filter(pk=dropped.pk).exists()
        author.refresh_from_db()
        assert author.name == "Ursula"
        assert result.service_result.changed_fields == ()
        assert [b["price"] for b in present(relations.update_author_spec, result)["books"]] == [
            "10.99",
            "8.00",
        ]

    def test_an_omitted_relation_is_left_alone(self, ada: Any) -> None:
        author = self._create(ada).value
        result = dispatch(
            relations.update_author_spec,
            principal=ada,
            arguments={"pk": author.pk, "name": "Ursula K. Le Guin"},
        )
        assert result.service_result.changed_fields == ("name",)
        assert not result.service_result.get_child_change("books")
        assert Book.objects.filter(author=author).count() == 2

    def test_an_explicit_empty_list_removes_every_row(self, ada: Any) -> None:
        author = self._create(ada).value
        result = dispatch(
            relations.update_author_spec,
            principal=ada,
            arguments={"pk": author.pk, "books": []},
        )
        assert len(result.service_result.get_child_change("books").deleted) == 2
        assert Book.objects.filter(author=author).count() == 0

    def test_the_create_dataclass_would_empty_an_update(self, ada: Any) -> None:
        # Why the page gives updates their own dataclass: AuthorIn's default
        # for an unsent ``books`` is ``[]``, which a replace reads as "none".
        author = self._create(ada).value
        data = declaring.author_validator.validate(
            {"name": "Ursula"}, ValidationContext(ada, author)
        )
        assert data["books"] == []
        change = update_from_input(author, data, relations=relations.BOOKS)
        assert len(change.get_child_change("books").deleted) == 2
        assert Book.objects.filter(author=author).count() == 0

    def test_a_row_the_author_does_not_own_is_refused_at_its_index(self, ada: Any) -> None:
        author = self._create(ada).value
        someone_else = Author.objects.create(name="Someone else")
        theirs = Book.objects.create(author=someone_else, title="Theirs", price="1.00")
        with pytest.raises(ServiceValidationError) as refused:
            dispatch(
                relations.update_author_spec,
                principal=ada,
                arguments={
                    "pk": author.pk,
                    "books": [{"pk": theirs.pk, "title": "Mine", "price": 1}],
                },
            )
        assert list(refused.value.detail) == ["books"]
        assert list(refused.value.detail["books"]) == [0]
        assert list(refused.value.detail["books"][0]) == ["non_field_errors"]
        theirs.refresh_from_db()
        assert theirs.title == "Theirs"

    def test_a_malformed_row_is_refused_before_the_service_runs(self, ada: Any) -> None:
        author = self._create(ada).value
        with pytest.raises(InvalidArguments) as refused:
            dispatch(
                relations.update_author_spec,
                principal=ada,
                arguments={
                    "pk": author.pk,
                    "books": [
                        {"title": "Fine", "price": "1"},
                        {"title": "Lost", "price": "1", "status": "lost"},
                    ],
                },
            )
        assert refused.value.detail == {
            "books": {
                1: {"status": ["Select a valid choice. lost is not one of the available choices."]}
            }
        }
        assert Book.objects.filter(author=author).count() == 2

    def test_a_delete_cascades_through_the_same_map_and_names_each_row(self, ada: Any) -> None:
        author = self._create(ada).value
        books = tuple(sorted(author.books.values_list("pk", flat=True)))
        result = dispatch(deleting.delete_author_spec, principal=ada, arguments={"pk": author.pk})
        assert result.kind == "instance"
        assert tuple(sorted(result.value)) == books
        assert not Author.objects.filter(pk=author.pk).exists()
        assert not Book.objects.filter(pk__in=books).exists()


class TestRegistry:
    def test_views_are_snapshots_in_the_order_asked_for(self) -> None:
        assert [e.name for e in registry.agent_tools] == ["list_notes", "rename_note"]
        assert [e.name for e in registry.command_line] == ["create_author", "list_notes"]
        assert [e.name for e in registry.registry.queries()] == ["list_notes"]
        assert registry.registry.specs()["rename_note"] is quickstart.rename_note_spec

    def test_a_later_registration_does_not_reach_an_earlier_view(self) -> None:
        source = SpecRegistry(registry.registry.all())
        view = source.by_tag("notes")
        source.register("show_note", dispatching.note_spec, tags=("notes",))
        assert "show_note" in source and "show_note" not in view

    def test_an_operation_with_no_permissions_is_refused_at_registration(self) -> None:
        undeclared = SelectorSpec(kind=SelectorKind.LIST, selector=Note.objects.none)
        with pytest.raises(ImproperlyConfigured, match=r"permissions=\[Unrestricted\(\)\]"):
            SpecRegistry().register("undeclared", undeclared)

    def test_chained_tags_intersect(self) -> None:
        writes = registry.registry.by_tag("catalogue").by_tag("write")
        assert [e.name for e in writes] == ["create_author", "update_author"]
        assert len(registry.registry.by_tag()) == 0

    def test_an_unknown_name_in_a_subset_is_refused(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            registry.registry.subset("list_notez")

    def test_merging_two_registries_that_share_a_name_is_refused(self) -> None:
        other = SpecRegistry()
        other.register("list_notes", declaring.list_notes_spec)
        with pytest.raises(ValueError, match="already registered"):
            registry.registry.merge(other)

    def test_only_a_spec_can_be_registered(self) -> None:
        with pytest.raises(TypeError, match="expected a ServiceSpec or SelectorSpec"):
            SpecRegistry().register("loose", quickstart.rename_note)

    def test_a_name_is_registered_once(self) -> None:
        with pytest.raises(ValueError, match="already registered"):
            SpecRegistry(registry.registry.all()).register("list_notes", declaring.list_notes_spec)


def _documented() -> list[tuple[str, str]]:
    """``(exported name, dotted path)`` for every ``:::`` entry in the reference page."""
    text = (ROOT / "docs" / "reference.md").read_text()
    paths = re.findall(r"^::: ([\w.]+)$", text, re.MULTILINE)
    return [(path.rsplit(".", 1)[1], path) for path in paths]


def _exporter(path: str) -> ModuleType:
    """Where a documented name is public: its optional adapter's subpackage, else the root."""
    for adapter in OPTIONAL_LIBRARY_ADAPTERS:
        if path.startswith(f"{adapter}."):
            return importlib.import_module(adapter)
    return django_service_specs


class TestReference:
    def test_every_public_name_has_a_reference_entry(self) -> None:
        # The root's names and, since the root cannot re-export them, each
        # optional-library adapter's own: public all the same.
        public = set(django_service_specs.__all__) - {"__version__"}
        for adapter in OPTIONAL_LIBRARY_ADAPTERS:
            public |= set(importlib.import_module(adapter).__all__)
        assert sorted(name for name, _ in _documented()) == sorted(public)

    def test_every_entry_names_the_object_the_package_exports(self) -> None:
        for name, path in _documented():
            module = importlib.import_module(path.rpartition(".")[0])
            assert getattr(module, name) is getattr(_exporter(path), name)
