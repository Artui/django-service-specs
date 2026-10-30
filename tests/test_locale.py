"""Tests for the package's translation catalog, ``django_service_specs/locale/``.

Every refusal's default message is a msgid in the shipped source catalog, and is
looked up in the active language when the refusal is constructed. These tests
translate through a real compiled catalog rather than a patched ``gettext``: a
patch would agree with any lookup, including one made once at import. The
catalog is written for a language Django ships none for (``xx``), so nothing but
the test's own catalog can answer, and it is compiled by ``_write_mo`` below
rather than ``msgfmt``, which not every machine running the suite has.
"""

from __future__ import annotations

import array
import ast
import os
import struct
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.apps import apps
from django.test import override_settings
from django.utils import translation
from django.utils.translation import trans_real

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.types.dispatch_error import DispatchError

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "django_service_specs"
SOURCE_CATALOG = PACKAGE_ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"

# No catalog Django or any installed app ships answers for this code, so a
# translated message can only have come from the catalog a test wrote.
LANGUAGE = "xx"

# Each refusal built with no message of its own, so it reads its default, and
# the English msgid it should look up. The msgids are literals rather than read
# off the class, so a refusal writing its looked-up message back onto the class
# fails here instead of moving the expectation along with it.
DEFAULTS: list[tuple[type[Exception], Callable[[], Exception], str]] = [
    (ServiceError, ServiceError, "Service error."),
    (ServiceNotFound, ServiceNotFound, "Not found."),
    (ServiceConflict, ServiceConflict, "Conflict."),
    (
        ActionUnavailable,
        lambda: ActionUnavailable(code="closed"),
        "This action is not available right now.",
    ),
    # A detail that is not a message gives way to the default.
    (
        ServiceValidationError,
        lambda: ServiceValidationError({"title": ["Too long."]}),
        "Service validation error.",
    ),
    (DispatchError, DispatchError, "The operation could not be dispatched."),
    (NotPermitted, NotPermitted, "You do not have permission to perform this action."),
    (PrincipalUnavailable, PrincipalUnavailable, "The acting principal is unavailable."),
    (InvalidArguments, lambda: InvalidArguments({"title": ["Too long."]}), "Invalid arguments."),
]
DEFAULT_IDS = [cls.__name__ for cls, _, _ in DEFAULTS]


def _refusal_classes() -> list[type[Exception]]:
    # Read off the class tree rather than listed, so a refusal added later is
    # held to the catalog without anyone remembering to add it here. Subclasses
    # a test declares are not the package's and carry no msgid.
    found: list[type[Exception]] = []
    pending: list[type[Exception]] = [ServiceError, DispatchError]
    while pending:
        cls = pending.pop()
        if cls.__module__.startswith("django_service_specs."):
            found.append(cls)
        pending.extend(cls.__subclasses__())
    return found


def _default_messages() -> set[str]:
    return {
        vars(cls)["default_message"] for cls in _refusal_classes() if "default_message" in vars(cls)
    }


def _write_mo(path: Path, messages: dict[str, str]) -> None:
    """Compile ``messages`` into a GNU ``.mo`` file, as ``msgfmt`` would.

    The format is a header, a table of (length, offset) pairs for the sorted
    msgids, one for their translations, then the NUL-terminated strings. The
    empty msgid is the catalog's header, and its charset is what makes the
    stdlib reader decode the strings as UTF-8 rather than ASCII.
    """
    catalog = {"": "Content-Type: text/plain; charset=UTF-8\n", **messages}
    keys = sorted(catalog)
    ids = strs = b""
    spans: list[tuple[int, int, int, int]] = []
    for key in keys:
        msgid, msgstr = key.encode(), catalog[key].encode()
        spans.append((len(ids), len(msgid), len(strs), len(msgstr)))
        ids += msgid + b"\0"
        strs += msgstr + b"\0"
    key_start = 7 * 4 + 16 * len(keys)
    value_start = key_start + len(ids)
    offsets: list[int] = []
    for id_offset, id_length, _, _ in spans:
        offsets += [id_length, id_offset + key_start]
    for _, _, str_offset, str_length in spans:
        offsets += [str_length, str_offset + value_start]
    header = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(header + array.array("i", offsets).tobytes() + ids + strs)


def _translated(msgid: str) -> str:
    return msgid.upper()


def _write_test_catalog(locale_dir: Path) -> None:
    _write_mo(
        locale_dir / LANGUAGE / "LC_MESSAGES" / "django.mo",
        {msgid: _translated(msgid) for _, _, msgid in DEFAULTS},
    )


def _msgids(po: Path) -> set[str]:
    # A msgid may run over several quoted lines, which the reader joins; the
    # header's empty msgid and obsolete (``#~``) entries are not messages.
    msgids: set[str] = set()
    current: list[str] | None = None
    for line in [*po.read_text(encoding="utf-8").splitlines(), ""]:
        if line.startswith("msgid "):
            current = [ast.literal_eval(line.removeprefix("msgid "))]
        elif line.startswith('"') and current is not None:
            current.append(ast.literal_eval(line))
        elif current is not None:
            msgids.add("".join(current))
            current = None
    msgids.discard("")
    return msgids


@pytest.fixture
def locale_paths(tmp_path: Path) -> Iterator[None]:
    # Changing LOCALE_PATHS fires Django's own setting_changed receiver, which
    # empties the translation cache on the way in and on the way out, so the
    # test catalog is read fresh and leaves nothing behind.
    _write_test_catalog(tmp_path)
    with override_settings(LOCALE_PATHS=[str(tmp_path)]):
        yield


@pytest.mark.parametrize(("cls", "build", "msgid"), DEFAULTS, ids=DEFAULT_IDS)
def test_each_refusal_declares_its_msgid(
    cls: type[Exception], build: Callable[[], Exception], msgid: str
) -> None:
    # Ties the literals above to the classes, and lists every refusal that
    # declares one, so a new member is added here rather than missed.
    assert vars(cls)["default_message"] == msgid
    assert sorted(c.__name__ for c in _refusal_classes() if "default_message" in vars(c)) == sorted(
        DEFAULT_IDS
    )


@pytest.mark.usefixtures("locale_paths")
@pytest.mark.parametrize(("cls", "build", "msgid"), DEFAULTS, ids=DEFAULT_IDS)
def test_a_default_message_is_read_in_the_active_language(
    cls: type[Exception], build: Callable[[], Exception], msgid: str
) -> None:
    with translation.override(LANGUAGE):
        error = build()
    assert (error.message, str(error)) == (_translated(msgid), _translated(msgid))


@pytest.mark.usefixtures("locale_paths")
@pytest.mark.parametrize(("cls", "build", "msgid"), DEFAULTS, ids=DEFAULT_IDS)
def test_nothing_is_frozen_at_import_or_at_the_last_call(
    cls: type[Exception], build: Callable[[], Exception], msgid: str
) -> None:
    # The class keeps the msgid, and each construction looks it up again: a
    # refusal built in another language before this one does not decide its words.
    with translation.override(LANGUAGE):
        build()
        assert vars(cls)["default_message"] == msgid
    assert build().message == msgid


@pytest.mark.usefixtures("locale_paths")
@pytest.mark.parametrize(
    "build",
    [
        ServiceError,
        ServiceNotFound,
        ServiceConflict,
        lambda message: ActionUnavailable(message, code="closed"),
        ServiceValidationError,
        DispatchError,
        NotPermitted,
        PrincipalUnavailable,
    ],
    ids=[
        "ServiceError",
        "ServiceNotFound",
        "ServiceConflict",
        "ActionUnavailable",
        "ServiceValidationError",
        "DispatchError",
        "NotPermitted",
        "PrincipalUnavailable",
    ],
)
def test_a_message_the_caller_passes_is_used_as_given(build: Callable[[str], Exception]) -> None:
    # Passed a string the test catalog does translate, so a lookup on the
    # caller's message would show.
    with translation.override(LANGUAGE):
        error = build("Not found.")
    assert error.message == "Not found."


def test_listing_the_app_loads_a_catalog_beside_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The route the docs give: Django reads ``<app path>/locale`` for every
    # installed app, which is where the shipped catalog sits. The app's path is
    # pointed at a copy holding a compiled test language, so the package's own
    # tree is never written to.
    config = apps.get_app_config("django_service_specs")
    assert SOURCE_CATALOG.is_relative_to(Path(config.path) / "locale")
    _write_test_catalog(tmp_path / "locale")
    monkeypatch.setattr(config, "path", str(tmp_path))
    monkeypatch.setattr(trans_real, "_translations", {})
    with translation.override(LANGUAGE):
        assert NotPermitted().message == _translated(
            "You do not have permission to perform this action."
        )


def test_the_source_catalog_lists_every_refusal_s_default_message() -> None:
    assert SOURCE_CATALOG.is_file()
    assert sorted(_default_messages() - _msgids(SOURCE_CATALOG)) == []


def test_the_source_catalog_keeps_django_rest_framework_s_msgids() -> None:
    # Spelled as DRF spells them, so a project with DRF installed keeps DRF's
    # translation of the four: ``NotFound``'s and ``PermissionDenied``'s
    # default details and ``ListField``'s two length messages.
    assert {
        "Not found.",
        "You do not have permission to perform this action.",
        "Ensure this field has no more than {max_length} elements.",
        "Ensure this field has at least {min_length} elements.",
    } <= _msgids(SOURCE_CATALOG)


def test_the_catalog_reader_joins_a_wrapped_msgid_and_skips_the_header(tmp_path: Path) -> None:
    po = tmp_path / "django.po"
    po.write_text(
        'msgid ""\nmsgstr ""\n"Language: \\n"\n\nmsgid ""\n"One "\n"two."\nmsgstr ""\n\n'
        '#~ msgid "Gone."\n#~ msgstr ""\n',
        encoding="utf-8",
    )
    assert _msgids(po) == {"One two."}


def test_marking_a_msgid_reads_no_setting() -> None:
    # Each default is marked when its class is defined, at import, and the
    # package imports before a project's settings are configured. Only the
    # lookup, made when a refusal is built with no message, reads them; one the
    # caller words needs none. A fresh interpreter with no settings module,
    # because this one is configured.
    probe = """
import django_service_specs
print(django_service_specs.NotPermitted("Ask the owner.").message)
"""
    env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "Ask the owner.\n"


def test_the_package_ships_the_source_language_and_no_translation() -> None:
    # A translated language is a contribution someone can review; until one is
    # reviewed and added, ``locale/`` holds the source catalog alone.
    assert sorted(path.name for path in (PACKAGE_ROOT / "locale").iterdir()) == ["en"]
