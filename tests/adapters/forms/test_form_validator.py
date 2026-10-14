from __future__ import annotations

import datetime as dt
import re
import tempfile
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import QuerySet
from django.test import RequestFactory, override_settings
from django.utils import translation
from django.utils.translation import gettext_lazy

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.http.request_arguments import request_arguments
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Author, Book, Document, Edition
from tests.parameters.utils import coded
from tests.relations_app.models import Post, Timestamped

User = get_user_model()

CONTEXT = ValidationContext(principal=None)

REQUIRED = "This field is required."


class Everything(forms.Form):
    """One field of every kind the adapter maps, in an order no table sorts into."""

    flag = forms.BooleanField()
    maybe = forms.NullBooleanField()
    count = forms.IntegerField()
    ratio = forms.FloatField(required=False)
    price = forms.DecimalField()
    at = forms.DateTimeField()
    on = forms.DateField(required=False)
    starts = forms.TimeField(required=False)
    lasts = forms.DurationField(required=False)
    name = forms.CharField(help_text="What the order is called.")
    email = forms.EmailField(required=False)
    token = forms.UUIDField(required=False)
    colour = forms.ChoiceField(
        choices=[
            ("", "---------"),
            ("Warm", [("red", "Red"), ("amber", "Amber")]),
            ("blue", "Blue"),
        ]
    )
    size = forms.TypedChoiceField(choices=[(1, "Small"), (2, "Large")], coerce=int)
    tags = forms.MultipleChoiceField(choices=[("a", "A"), ("b", "B")], required=False)
    scores = forms.TypedMultipleChoiceField(
        choices=[(1, "One"), (2, "Two")], coerce=int, required=False
    )
    author = forms.ModelChoiceField(queryset=Author.objects.all())
    books = forms.ModelMultipleChoiceField(queryset=Book.objects.all(), required=False)


class Username(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["author", "title", "price", "status"]


class _NoModel(forms.ModelForm):
    """A ModelForm Django accepts as a class and refuses only when one is built."""


_BEYOND_THE_COLUMN = 2**63
"""One past the largest key SQLite's integer column holds, and so past every backend's."""


def _many_books() -> forms.ModelMultipleChoiceField:
    return forms.ModelMultipleChoiceField(queryset=Book.objects.all())


def _form(form_name: str, /, **fields: forms.Field) -> type[forms.Form]:
    return type(form_name, (forms.Form,), fields)


def _declared(form_class: type[forms.BaseForm]) -> list[tuple[Any, ...]]:
    return [
        (p.name, p.type, p.format, p.items, p.choices, p.required, p.nullable)
        for p in FormValidator(form_class).parameters()
    ]


def _refusal(
    form_class: type[forms.BaseForm], arguments: dict[str, Any], target: Any = None
) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        FormValidator(form_class).validate(arguments, ValidationContext(None, target))
    return caught.value.detail


class TestConstruction:
    @pytest.mark.parametrize(
        "given",
        [dict, Everything(), Username.Meta],
        ids=["another-class", "a-form-instance", "a-meta-class"],
    )
    def test_refuses_anything_but_a_form_class(self, given: Any) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape(f"FormValidator takes a Django form class; got {given!r}."),
        ):
            FormValidator(given)

    def test_a_model_form_with_no_model_is_refused_where_it_is_declared(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape("_NoModel: a ModelForm with no Meta.model cannot be bound;"),
        ):
            FormValidator(_NoModel)

    @pytest.mark.parametrize(
        ("field", "message"),
        [
            (
                forms.JSONField(),
                "Upload.field: a JSONField takes any JSON value, and a parameter declares "
                "one JSON type.",
            ),
            (
                forms.SplitDateTimeField(),
                "Upload.field: a SplitDateTimeField is cleaned from several widget values "
                "at once, which only an HTML form sends; declare a field per value.",
            ),
            (
                forms.ComboField(fields=[forms.CharField(), forms.EmailField()]),
                "Upload.field: a ComboField cleans one value through several fields, and "
                "has no JSON type of its own.",
            ),
            (
                forms.Field(),
                "Upload.field: a Field is not a field this adapter can declare. It declares "
                "BooleanField,",
            ),
        ],
    )
    def test_a_field_with_no_json_type_is_refused_at_construction(
        self, field: forms.Field, message: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match=re.escape(message)):
            FormValidator(_form("Upload", field=field))

    def test_a_field_of_a_class_the_table_does_not_cover_is_refused(self) -> None:
        class Colour(forms.Field):
            """A field a project wrote, with no JSON type the adapter could know."""

        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape("Palette.primary: a Colour is not a field this adapter can declare."),
        ):
            FormValidator(_form("Palette", primary=Colour()))


class TestParameters:
    def test_every_mapped_field_declares_its_json_type_in_declaration_order(self) -> None:
        assert _declared(Everything) == [
            ("flag", "boolean", None, None, None, True, False),
            ("maybe", "boolean", None, None, None, False, True),
            ("count", "integer", None, None, None, True, False),
            ("ratio", "number", None, None, None, False, True),
            ("price", "string", "decimal", None, None, True, False),
            ("at", "string", "date-time", None, None, True, False),
            ("on", "string", "date", None, None, False, True),
            ("starts", "string", None, None, None, False, True),
            ("lasts", "string", None, None, None, False, True),
            ("name", "string", None, None, None, True, False),
            ("email", "string", None, None, None, False, True),
            ("token", "string", None, None, None, False, True),
            ("colour", "string", None, None, ("red", "amber", "blue"), True, False),
            ("size", "integer", None, None, (1, 2), True, False),
            ("tags", "array", None, "string", ("a", "b"), False, True),
            ("scores", "array", None, "integer", (1, 2), False, True),
            ("author", "integer", None, None, None, True, False),
            ("books", "array", None, "integer", None, False, True),
        ]

    def test_no_parameter_declares_a_default_even_with_an_initial(self) -> None:
        form_class = _form("Greeting", text=forms.CharField(initial="Hello", required=False))
        (text,) = FormValidator(form_class).parameters()
        assert text.default is UNSET
        # And the form agrees: an absent optional field cleans to its empty value.
        assert FormValidator(form_class).validate({}, CONTEXT) == {"text": ""}

    def test_help_is_the_help_text_and_none_without_one(self) -> None:
        params = FormValidator(Everything).parameters()
        assert [(p.name, p.help) for p in params if p.help is not None] == [
            ("name", "What the order is called.")
        ]

    def test_help_is_read_on_each_call_in_the_active_language(self) -> None:
        form_class = _form("Lazy", text=forms.CharField(help_text=gettext_lazy(REQUIRED)))
        validator = FormValidator(form_class)
        with translation.override("de"):
            (text,) = validator.parameters()
        assert text.help == "Dieses Feld ist zwingend erforderlich."
        (text,) = validator.parameters()
        assert text.help == REQUIRED

    @pytest.mark.django_db
    def test_reading_a_declaration_never_queries(self, django_assert_num_queries: Any) -> None:
        with django_assert_num_queries(0):
            FormValidator(Everything).parameters()
            FormValidator(BookForm).parameters()

    def test_every_array_declares_its_items_as_a_type_name(self) -> None:
        # What coerce_flat reads an array's elements by; nested Parameters
        # would have no flat spelling.
        arrays = [p for p in FormValidator(Everything).parameters() if p.type == "array"]
        assert [(p.name, p.items) for p in arrays] == [
            ("tags", "string"),
            ("scores", "integer"),
            ("books", "integer"),
        ]

    def test_a_disabled_field_is_not_a_parameter_and_cleans_to_its_initial(self) -> None:
        form_class = _form(
            "Order",
            sku=forms.CharField(),
            channel=forms.CharField(disabled=True, initial="web"),
        )
        validator = FormValidator(form_class)
        assert [p.name for p in validator.parameters()] == ["sku"]
        assert validator.validate({"sku": "A-1", "channel": "phone"}, CONTEXT) == {
            "sku": "A-1",
            "channel": "web",
        }

    def test_a_field_added_in_init_is_not_described_and_the_closed_set_refuses_it(
        self,
    ) -> None:
        class Dynamic(forms.Form):
            name = forms.CharField()

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.fields["nickname"] = forms.CharField()

        params = FormValidator(Dynamic).parameters()
        assert [p.name for p in params] == ["name"]
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(params, {"name": "Ada", "nickname": "A"})
        assert refused.value.detail == {"nickname": ["Unknown argument."]}


class TestChoices:
    def test_a_plain_choice_field_declares_its_choices_as_the_strings_it_compares(
        self,
    ) -> None:
        form_class = _form("Rating", stars=forms.ChoiceField(choices=[(1, "One"), (2, "Two")]))
        assert _declared(form_class) == [("stars", "string", None, None, ("1", "2"), True, False)]
        # The form cleans with ``str``: the string is what it takes and returns.
        assert FormValidator(form_class).validate({"stars": "2"}, CONTEXT) == {"stars": "2"}

    def test_an_option_group_given_as_a_tuple_is_flattened_too(self) -> None:
        # Django 5.0 and later normalise every group to a list; 4.2 keeps the
        # tuple it was given, which is the case this holds.
        form_class = _form(
            "Shade",
            shade=forms.ChoiceField(choices=(("Warm", (("red", "Red"), ("amber", "Amber"))),)),
        )
        assert _declared(form_class) == [
            ("shade", "string", None, None, ("red", "amber"), True, False)
        ]

    def test_none_is_dropped_as_the_empty_choice_too(self) -> None:
        form_class = _form(
            "Level",
            level=forms.TypedChoiceField(choices=[(None, "Unknown"), (1, "Low")], coerce=int),
        )
        assert _declared(form_class) == [("level", "integer", None, None, (1,), True, False)]

    @pytest.mark.parametrize(
        ("choices", "json_type"),
        [
            ([(True, "Yes"), (False, "No")], "boolean"),
            ([(1, "One"), (2, "Two")], "integer"),
            ([(0.5, "Half"), (1.5, "More")], "number"),
            ([("s", "Small"), ("l", "Large")], "string"),
        ],
    )
    def test_a_typed_choice_fields_values_decide_its_json_type(
        self, choices: list[tuple[Any, str]], json_type: str
    ) -> None:
        form_class = _form("Pick", value=forms.TypedChoiceField(choices=choices))
        (value,) = FormValidator(form_class).parameters()
        assert (value.type, value.choices) == (json_type, tuple(v for v, _ in choices))

    @pytest.mark.parametrize(
        "choices",
        [
            [(1, "One"), ("two", "Two")],
            [(Decimal("1.5"), "One and a half")],
        ],
    )
    def test_typed_choices_sharing_no_json_type_are_refused(
        self, choices: list[tuple[Any, str]]
    ) -> None:
        values = [v for v, _ in choices]
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape(
                f"Pick.value: a TypedChoiceField whose values {values!r} share no JSON type "
                "cannot be declared;"
            ),
        ):
            FormValidator(_form("Pick", value=forms.TypedChoiceField(choices=choices)))

    def test_a_typed_choice_field_with_only_the_empty_choice_takes_a_string(self) -> None:
        form_class = _form("Pick", value=forms.TypedChoiceField(choices=[("", "---------")]))
        assert _declared(form_class) == [("value", "string", None, None, (), True, False)]

    @pytest.mark.parametrize("field_class", [forms.ChoiceField, forms.TypedChoiceField])
    def test_a_callable_choice_set_is_not_read(self, field_class: type[forms.Field]) -> None:
        calls: list[int] = []

        def colours() -> list[tuple[str, str]]:
            calls.append(1)
            return [("red", "Red")]

        form_class = _form("Paint", colour=field_class(choices=colours))
        validator = FormValidator(form_class)
        assert _declared(form_class) == [("colour", "string", None, None, None, True, False)]
        assert calls == []
        # The form still checks the choice, reading the set when it is built.
        assert validator.validate({"colour": "red"}, CONTEXT) == {"colour": "red"}
        assert _refusal(form_class, {"colour": "blue"}) == {
            "colour": ["Select a valid choice. blue is not one of the available choices."]
        }


class TestModelChoices:
    @pytest.mark.parametrize(
        ("queryset", "to_field_name", "json_type", "fmt"),
        [
            (Book.objects.all(), None, "integer", None),
            (Book.objects.all(), "title", "string", None),
            (Book.objects.all(), "price", "string", "decimal"),
            (Book.objects.all(), "published_on", "string", "date"),
            (Timestamped.objects.all(), "created_at", "string", "date-time"),
            (Post.objects.all(), "body", "string", None),
            # A foreign key is matched on what it holds: the related row's key.
            (Book.objects.all(), "author", "integer", None),
        ],
    )
    def test_the_type_is_that_of_the_model_field_rows_are_matched_on(
        self, queryset: Any, to_field_name: str | None, json_type: str, fmt: str | None
    ) -> None:
        field = forms.ModelChoiceField(queryset=queryset, to_field_name=to_field_name)
        assert _declared(_form("Pick", row=field)) == [
            ("row", json_type, fmt, None, None, True, False)
        ]

    @pytest.mark.parametrize(
        ("to_field_name", "json_type", "fmt"),
        [
            (None, "integer", None),
            ("price", "string", "decimal"),
            # A date takes no format on an array, so a list of them stays an
            # array of strings: without the decimal condition in
            # ``element_format`` this field could not be declared.
            ("published_on", "string", None),
        ],
    )
    def test_a_list_of_keys_declares_each_element_a_decimal_as_one_key_does(
        self, to_field_name: str | None, json_type: str, fmt: str | None
    ) -> None:
        field = forms.ModelMultipleChoiceField(
            queryset=Book.objects.all(), to_field_name=to_field_name
        )
        (rows,) = FormValidator(_form("Pick", rows=field)).parameters()
        assert (rows.type, rows.items, rows.format) == ("array", json_type, fmt)

    def test_a_query_string_splits_a_list_of_decimal_keys_on_its_commas(self) -> None:
        field = forms.ModelMultipleChoiceField(queryset=Book.objects.all(), to_field_name="price")
        parameters = FormValidator(_form("Pick", rows=field)).parameters()
        request = RequestFactory().get("/", {"rows": "12.50,9.99"})
        assert request_arguments(request, parameters) == {"rows": ["12.50", "9.99"]}

    @pytest.mark.django_db
    def test_a_list_of_decimal_keys_is_matched_on_the_column_s_own_spelling(self) -> None:
        # The shape check reads each element as a decimal, a JSON number
        # included, and hands it on as sent. Django's field then matches each
        # value against the ``str`` of the rows' column, so ``"12.50"`` names
        # the row a two-place column holds and ``12.5`` names none: the form's
        # refusal, in its words, where a list of strings was refused by type.
        author = Author.objects.create(name="Ursula")
        book = Book.objects.create(author=author, title="Lathe", price=Decimal("12.50"))
        field = forms.ModelMultipleChoiceField(queryset=Book.objects.all(), to_field_name="price")
        validator = FormValidator(_form("Pick", rows=field))
        arguments = check_arguments(validator.parameters(), {"rows": ["12.50"]})
        assert list(validator.validate(arguments, CONTEXT)["rows"]) == [book]
        arguments = check_arguments(validator.parameters(), {"rows": [12.5]})
        assert coded(_refusal(validator.form_class, arguments)) == {
            "rows": [
                (
                    "Select a valid choice. 12.5 is not one of the available choices.",
                    "invalid_choice",
                )
            ]
        }

    @pytest.mark.django_db
    @pytest.mark.parametrize("key", [_BEYOND_THE_COLUMN, -_BEYOND_THE_COLUMN - 1])
    def test_a_list_naming_a_key_past_the_column_s_range_is_no_choice(self, key: int) -> None:
        # Django's ``ModelMultipleChoiceField`` matches the list with an
        # ``__in`` lookup, which hands a key past the integer column's range
        # to the database driver and raises ``OverflowError`` on every Django
        # version. No row can hold that key, so the list is no choice: refused
        # in the field's own words, beside the form's other refusals.
        validator = FormValidator(_form("Pick", rows=_many_books(), title=forms.CharField()))
        arguments = check_arguments(validator.parameters(), {"rows": [key], "title": "Lathe"})
        assert coded(_refusal(validator.form_class, {**arguments, "title": ""})) == {
            "title": [("This field is required.", "required")],
            "rows": [
                (
                    f"Select a valid choice. {key} is not one of the available choices.",
                    "invalid_choice",
                )
            ],
        }

    @pytest.mark.django_db
    def test_django_s_own_list_field_hands_such_a_key_to_the_driver(self) -> None:
        # Why the adapter answers first: the field alone raises, on every
        # Django version the package supports. Fails, and says the adapter's
        # check can go, once Django answers it.
        with pytest.raises(OverflowError):
            _many_books().clean([_BEYOND_THE_COLUMN])

    @pytest.mark.django_db
    @pytest.mark.parametrize("key", [_BEYOND_THE_COLUMN, -_BEYOND_THE_COLUMN - 1])
    def test_a_key_past_the_column_s_range_is_no_choice(self, key: int) -> None:
        # Django 5.0 answers an exact lookup past the range with no rows, so
        # ``ModelChoiceField`` refuses it there; Django 4.2 raises
        # ``OverflowError`` from its ``get``. Refused before the query, the
        # answer is the field's own on both.
        field = forms.ModelChoiceField(queryset=Book.objects.all())
        validator = FormValidator(_form("Pick", row=field))
        arguments = check_arguments(validator.parameters(), {"row": key})
        assert coded(_refusal(validator.form_class, arguments)) == {
            "row": [
                (
                    "Select a valid choice. That choice is not one of the available choices.",
                    "invalid_choice",
                )
            ]
        }

    @pytest.mark.django_db
    def test_the_keys_at_either_end_of_the_column_s_range_are_matched(self) -> None:
        author = Author.objects.create(name="Ursula")
        ends = [
            Book.objects.create(pk=key, author=author, title="End", price=Decimal("1.00"))
            for key in (-_BEYOND_THE_COLUMN, _BEYOND_THE_COLUMN - 1)
        ]
        validator = FormValidator(
            _form(
                "Pick", rows=_many_books(), row=forms.ModelChoiceField(queryset=Book.objects.all())
            )
        )
        cleaned = validator.validate(
            {"rows": [book.pk for book in ends], "row": ends[1].pk}, CONTEXT
        )
        assert (sorted(book.pk for book in cleaned["rows"]), cleaned["row"]) == (
            [book.pk for book in ends],
            ends[1],
        )

    @pytest.mark.django_db
    def test_a_key_past_an_integer_range_on_a_text_column_is_matched(self) -> None:
        # Only an integer column has a range: a title is matched as the text
        # the integer spells, as Django matches it.
        author = Author.objects.create(name="Ursula")
        book = Book.objects.create(
            author=author, title=str(_BEYOND_THE_COLUMN), price=Decimal("1.00")
        )
        field = forms.ModelMultipleChoiceField(queryset=Book.objects.all(), to_field_name="title")
        validator = FormValidator(_form("Pick", rows=field))
        assert list(validator.validate({"rows": [_BEYOND_THE_COLUMN]}, CONTEXT)["rows"]) == [book]

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    @pytest.mark.parametrize("many", [False, True], ids=["one", "a-list"])
    def test_a_key_spelled_as_digits_past_the_column_s_range_is_no_choice(self, many: bool) -> None:
        # A caller handing ``validate`` the string, where dispatch's shape
        # check hands on an ``int``: the field's lookup reads the digits as
        # the integer they spell, and handed that to the driver.
        key = str(_BEYOND_THE_COLUMN)
        if many:
            form_class = _form("Pick", rows=_many_books())
            arguments: dict[str, Any] = {"rows": [key]}
            message = f"Select a valid choice. {key} is not one of the available choices."
        else:
            form_class = _form("Pick", rows=forms.ModelChoiceField(queryset=Book.objects.all()))
            arguments = {"rows": key}
            message = "Select a valid choice. That choice is not one of the available choices."
        assert coded(_refusal(form_class, arguments)) == {"rows": [(message, "invalid_choice")]}

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_a_key_that_spells_no_number_is_the_field_s(self) -> None:
        # The column's lookup refuses ``"abc"`` with a ValueError, which the
        # field catches and answers in its words.
        form_class = _form("Pick", rows=_many_books())
        assert coded(_refusal(form_class, {"rows": ["abc"]})) == {
            "rows": [("\u201cabc\u201d is not a valid value.", "invalid_pk_value")]
        }

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_an_optional_key_sent_as_null_is_the_field_s(self) -> None:
        # ``None`` names no number, so no range is compared with it.
        field = forms.ModelChoiceField(queryset=Book.objects.all(), required=False)
        assert FormValidator(_form("Pick", row=field)).validate({"row": None}, CONTEXT) == {
            "row": None
        }

    @pytest.mark.django_db
    def test_a_key_sent_as_a_string_is_left_to_the_field(self) -> None:
        # Dispatch's shape check hands an integer key on as an ``int``; a
        # caller handing ``validate`` the string is answered by the field.
        author = Author.objects.create(name="Ursula")
        book = Book.objects.create(author=author, title="Lathe", price=Decimal("1.00"))
        validator = FormValidator(_form("Pick", rows=_many_books()))
        assert list(validator.validate({"rows": [str(book.pk)]}, CONTEXT)["rows"]) == [book]

    def test_a_list_of_rows_declares_no_length_and_the_setting_bounds_it(self) -> None:
        field = forms.ModelMultipleChoiceField(queryset=Book.objects.all())
        (rows,) = FormValidator(_form("Pick", rows=field)).parameters()
        assert (rows.min_length, rows.max_length) == (None, None)
        with (
            override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=2),
            pytest.raises(InvalidArguments) as caught,
        ):
            check_arguments(Parameters.of(rows), {"rows": [1, 2, 3]})
        assert coded(caught.value.detail) == {
            "rows": [("Ensure this field has no more than 2 elements.", "max_length")]
        }

    def test_a_key_with_no_json_type_is_refused(self) -> None:
        field = forms.ModelChoiceField(queryset=Post.objects.all(), to_field_name="published")
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape(
                "Pick.post: matches rows on relations_app.Post.published, a BooleanField, "
                "which has no JSON type this adapter can declare."
            ),
        ):
            FormValidator(_form("Pick", post=field))

    def test_a_model_choice_field_with_no_queryset_is_refused(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape(
                "Pick.post: a ModelMultipleChoiceField with no queryset has no model to "
                "read its key from;"
            ),
        ):
            FormValidator(_form("Pick", post=forms.ModelMultipleChoiceField(queryset=None)))


class TestPresence:
    def test_a_required_boolean_field_refuses_absent_and_false_alike(self) -> None:
        form_class = _form("Terms", accepted=forms.BooleanField())
        (accepted,) = FormValidator(form_class).parameters()
        assert (accepted.required, accepted.nullable) == (True, False)
        assert _refusal(form_class, {}) == {"accepted": [REQUIRED]}
        assert _refusal(form_class, {"accepted": False}) == {"accepted": [REQUIRED]}
        # And the shape check, reading the declaration, refuses the absent one first.
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(FormValidator(form_class).parameters(), {})
        assert refused.value.detail == {"accepted": [REQUIRED]}

    def test_an_optional_boolean_field_cleans_absent_and_null_to_false(self) -> None:
        validator = FormValidator(_form("News", subscribe=forms.BooleanField(required=False)))
        assert validator.validate({}, CONTEXT) == {"subscribe": False}
        assert validator.validate({"subscribe": None}, CONTEXT) == {"subscribe": False}

    def test_a_null_boolean_field_is_never_required_whatever_it_says(self) -> None:
        form_class = _form("Survey", answer=forms.NullBooleanField(required=True))
        assert _declared(form_class) == [("answer", "boolean", None, None, None, False, True)]
        validator = FormValidator(form_class)
        assert validator.validate({}, CONTEXT) == {"answer": None}
        assert validator.validate({"answer": None}, CONTEXT) == {"answer": None}
        assert validator.validate({"answer": False}, CONTEXT) == {"answer": False}

    @pytest.mark.parametrize(
        ("make", "empty"),
        [
            (forms.CharField, ""),
            (forms.IntegerField, None),
            (forms.DateTimeField, None),
            (lambda **kw: forms.ChoiceField(choices=[("a", "A")], **kw), ""),
            (lambda **kw: forms.MultipleChoiceField(choices=[("a", "A")], **kw), []),
            (lambda **kw: forms.ModelChoiceField(queryset=Author.objects.all(), **kw), None),
            (forms.BooleanField, False),
        ],
    )
    def test_the_shape_check_and_the_form_agree_on_null(
        self, make: Callable[..., forms.Field], empty: Any
    ) -> None:
        required = FormValidator(_form("Strict", value=make()))
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(required.parameters(), {"value": None})
        assert refused.value.detail == {"value": ["This field cannot be null."]}
        assert _refusal(required.form_class, {"value": None}) == {"value": [REQUIRED]}

        optional = FormValidator(_form("Lenient", value=make(required=False)))
        assert check_arguments(optional.parameters(), {"value": None}) == {"value": None}
        assert optional.validate({"value": None}, CONTEXT) == {"value": empty}

    def test_the_empty_choice_is_sent_as_null_not_as_an_empty_string(self) -> None:
        form_class = _form(
            "Paint", colour=forms.ChoiceField(choices=[("red", "Red")], required=False)
        )
        params = FormValidator(form_class).parameters()
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(params, {"colour": ""})
        assert refused.value.detail == {
            "colour": ["Select a valid choice.  is not one of the available choices."]
        }
        assert check_arguments(params, {"colour": None}) == {"colour": None}
        assert FormValidator(form_class).validate({"colour": None}, CONTEXT) == {"colour": ""}


@pytest.mark.django_db
class TestValidate:
    def _arguments(self, author: Author, **overrides: Any) -> dict[str, Any]:
        """Arguments for ``Everything`` as a JSON wire would carry them."""
        return {
            "flag": True,
            "count": 3,
            "price": 12.5,
            "at": "2024-06-01T12:00:00+02:00",
            "name": "Order",
            "colour": "amber",
            "size": 2,
            "tags": ["a", "b"],
            "scores": [2],
            "author": author.pk,
            **overrides,
        }

    def test_json_typed_values_validate_to_what_the_form_cleans(self) -> None:
        author = Author.objects.create(name="Ada")
        book = Book.objects.create(author=author, title="Notes", price=Decimal("1.00"))
        arguments = self._arguments(author, books=[book.pk], ratio=1)
        # Exactly what the kernel's own check lets through, so nothing is lost there.
        assert check_arguments(FormValidator(Everything).parameters(), arguments) == arguments
        cleaned = FormValidator(Everything).validate(arguments, CONTEXT)
        assert {k: v for k, v in cleaned.items() if k != "books"} == {
            "flag": True,
            "maybe": None,
            "count": 3,
            "ratio": 1.0,
            "price": Decimal("12.5"),
            "at": dt.datetime(2024, 6, 1, 10, 0, tzinfo=dt.timezone.utc),
            "on": None,
            "starts": None,
            "lasts": None,
            "name": "Order",
            "email": "",
            "token": None,
            "colour": "amber",
            "size": 2,
            "tags": ["a", "b"],
            "scores": [2],
            "author": author,
        }
        # The multiple one cleans to a queryset, which is what the service receives.
        assert isinstance(cleaned["books"], QuerySet)
        assert list(cleaned["books"]) == [book]

    def test_flat_strings_reach_the_form_through_coerce_flat_and_the_shape_check(self) -> None:
        author = Author.objects.create(name="Ada")
        params = FormValidator(Everything).parameters()
        raw = {
            "flag": "true",
            "count": "3",
            "price": "12.50",
            "at": "2024-06-01T12:00:00+00:00",
            "name": "Order",
            "colour": "red",
            "size": "1",
            "tags": "a",
            "author": str(author.pk),
        }
        checked = check_arguments(params, coerce_flat(params, raw))
        cleaned = FormValidator(Everything).validate(checked, CONTEXT)
        assert (cleaned["flag"], cleaned["count"], cleaned["size"], cleaned["tags"]) == (
            True,
            3,
            1,
            ["a"],
        )
        assert cleaned["author"] == author

    def test_a_refusal_carries_the_forms_own_messages_by_field(self) -> None:
        form_class = _form("Contact", code=forms.CharField(max_length=3), email=forms.EmailField())
        arguments = {"code": "ABCD", "email": "not-an-address"}
        # Nothing the declaration can see is wrong, so each message is the form's.
        assert check_arguments(FormValidator(form_class).parameters(), arguments) == arguments
        assert _refusal(form_class, arguments) == {
            "code": ["Ensure this value has at most 3 characters (it has 4)."],
            "email": ["Enter a valid email address."],
        }

    def test_a_form_wide_error_is_moved_to_non_field_errors(self) -> None:
        class Window(forms.Form):
            opens = forms.IntegerField()
            closes = forms.IntegerField()

            def clean(self) -> dict[str, Any]:
                cleaned = super().clean() or {}
                if cleaned["closes"] <= cleaned["opens"]:
                    raise forms.ValidationError("A window closes after it opens.")
                return cleaned

        detail = _refusal(Window, {"opens": 9, "closes": 5})
        assert detail == {"non_field_errors": ["A window closes after it opens."]}
        assert "__all__" not in detail

    def test_every_leaf_is_a_list_of_str(self) -> None:
        detail = _refusal(_form("Pair", a=forms.IntegerField(max_value=1)), {"a": 2})
        assert detail == {"a": ["Ensure this value is less than or equal to 1."]}
        # A ``str`` each, never a lazy translation or Django's error object,
        # carrying the field's own code beside its words.
        assert all(isinstance(m, str) for messages in detail.values() for m in messages)
        assert coded(detail) == {
            "a": [("Ensure this value is less than or equal to 1.", "max_value")]
        }

    def test_the_form_is_built_from_the_arguments_alone(self) -> None:
        class ForUser(forms.Form):
            name = forms.CharField()

            def __init__(self, *args: Any, user: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)

        with pytest.raises(TypeError, match="user"):
            FormValidator(ForUser).validate({"name": "Ada"}, ValidationContext(principal=object()))

    def test_an_argument_no_field_declares_is_ignored_by_the_form(self) -> None:
        validator = FormValidator(_form("Named", name=forms.CharField()))
        assert validator.validate({"name": "Ada", "colour": "red"}, CONTEXT) == {"name": "Ada"}


class TestTheWireFormIsNotLocalized:
    """An argument is in its wire form, and a localized field must not read it as the locale's."""

    @pytest.fixture
    def german(self, settings: Any) -> Any:
        # A locale whose thousands separator is a dot, with separators read.
        settings.USE_THOUSAND_SEPARATOR = True
        with translation.override("de"):
            yield

    def test_a_decimal_with_three_places_is_not_read_as_thousands(self, german: Any) -> None:
        # Bound as the string, the field read "1.500" as fifteen hundred: a
        # person typing 1,500 on a German form was sent on as 1500.
        form_class = _form("Priced", price=forms.DecimalField(localize=True, decimal_places=3))
        cleaned = FormValidator(form_class).validate({"price": "1.500"}, CONTEXT)
        assert cleaned == {"price": Decimal("1.500")}

    def test_a_field_that_is_not_a_number_is_bound_as_it_came(self, german: Any) -> None:
        # A postcode spells a number and is not one: made a Decimal, it lost
        # its leading zero.
        form_class = _form("Addressed", postcode=forms.CharField(localize=True))
        cleaned = FormValidator(form_class).validate({"postcode": "01234"}, CONTEXT)
        assert cleaned == {"postcode": "01234"}

    def test_a_json_number_for_a_decimal_is_bound_as_it_came(self) -> None:
        # The shape check accepts a JSON number for a decimal. Made a Decimal,
        # 0.1 carries its binary expansion and fails the field's two places.
        form_class = _form("Priced", price=forms.DecimalField(decimal_places=2))
        cleaned = FormValidator(form_class).validate({"price": 0.1}, CONTEXT)
        assert cleaned == {"price": Decimal("0.1")}

    def test_a_string_that_is_no_number_is_refused_by_the_field(self) -> None:
        form_class = _form("Priced", price=forms.DecimalField())
        with pytest.raises(InvalidArguments) as refused:
            FormValidator(form_class).validate({"price": "cheap"}, CONTEXT)
        assert refused.value.detail == {"price": ["Enter a number."]}


class _Viewed(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["title", "views"]


def _form_over_views(views: forms.Field) -> type[forms.ModelForm]:
    """A ``ModelForm`` over ``Post`` declaring its integer column ``views`` as ``views``."""
    return type("Viewed", (_Viewed,), {"views": views})


class TestANumberPastItsRange:
    """An integer no float, no ``str`` or no column holds is refused, never raised."""

    @pytest.mark.parametrize("value", [10**400, -(10**400)], ids=["above", "below"])
    def test_an_integer_past_a_float_s_range_is_the_field_s_invalid_number(
        self, value: int
    ) -> None:
        # JSON's number has no range, so the shape check hands the integer on,
        # and the field's ``float`` raised OverflowError. A string of the same
        # digits reads as infinity, which the field refuses as no number.
        form_class = _form("Measured", ratio=forms.FloatField())
        assert coded(_refusal(form_class, {"ratio": value})) == {
            "ratio": [("Enter a number.", "invalid")]
        }

    def test_an_integer_past_a_float_s_range_is_refused_in_the_field_s_own_words(self) -> None:
        field = forms.FloatField(error_messages={"invalid": "Not a ratio."})
        assert coded(_refusal(_form("Measured", ratio=field), {"ratio": 10**400})) == {
            "ratio": [("Not a ratio.", "invalid")]
        }

    def test_a_float_field_still_reads_an_integer_as_its_float(self) -> None:
        form_class = _form("Measured", ratio=forms.FloatField())
        cleaned = FormValidator(form_class).validate({"ratio": 2**53 + 1}, CONTEXT)
        assert cleaned == {"ratio": float(2**53 + 1)}

    def test_a_decimal_sent_as_an_integer_is_read_whatever_its_digits(self) -> None:
        # The field reads a value through ``str``, which refuses an int past
        # 4300 digits from Python 3.10.7 on, with a ValueError the field does
        # not catch. A Decimal's ``str`` has no such limit.
        form_class = _form("Priced", price=forms.DecimalField())
        cleaned = FormValidator(form_class).validate({"price": 10**5000}, CONTEXT)
        assert cleaned == {"price": Decimal(10**5000)}

    def test_true_is_still_no_decimal_to_the_field(self) -> None:
        # Python makes a bool an int, and ``Decimal(True)`` is one; bound as it
        # came, the field reads ``"True"`` and refuses it.
        form_class = _form("Priced", price=forms.DecimalField())
        assert _refusal(form_class, {"price": True}) == {"price": ["Enter a number."]}

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    @pytest.mark.parametrize(
        ("views", "refusal"),
        [
            (2**63, ("less than or equal to", 2**63 - 1, "max_value")),
            (-(2**63) - 1, ("greater than or equal to", -(2**63), "min_value")),
            (str(2**63), ("less than or equal to", 2**63 - 1, "max_value")),
        ],
        ids=["above", "below", "digits"],
    )
    def test_a_value_past_an_integer_column_s_range_is_refused_in_django_s_words(
        self, views: Any, refusal: tuple[str, int, str]
    ) -> None:
        # The words Django's model validators use from 5.0, where the backend
        # states the range; where it states none, Django took the value and
        # the column could not hold it. Digits are the integer the field
        # cleans them to, as Django's validators read it.
        words, limit, code = refusal
        detail = _refusal(_Viewed, {"title": "Hi", "views": views})
        assert coded(detail) == {"views": [(f"Ensure this value is {words} {limit}.", code)]}

    @pytest.mark.django_db
    def test_a_field_s_own_limit_answers_before_the_column_s(self) -> None:
        # As where Django validates the model: the field refuses first, and
        # the model is never asked about it.
        form_class = _form_over_views(forms.IntegerField(max_value=100))
        assert coded(_refusal(form_class, {"title": "Hi", "views": 2**63})) == {
            "views": [("Ensure this value is less than or equal to 100.", "max_value")]
        }

    @pytest.mark.django_db
    def test_an_optional_integer_left_out_is_the_field_s(self) -> None:
        form_class = _form_over_views(forms.IntegerField(required=False))
        assert FormValidator(form_class).validate({"title": "Hi"}, CONTEXT) == {
            "title": "Hi",
            "views": None,
        }

    @pytest.mark.django_db
    def test_a_clean_method_handing_back_nothing_is_the_model_s(self) -> None:
        # Required, so Django validates the column with what the method hands
        # back, and ``None`` is no number to range: the model refuses it.
        class Emptied(_Viewed):
            def clean_views(self) -> None:
                return None

        assert coded(_refusal(Emptied, {"title": "Hi", "views": 5})) == {
            "views": [("This field cannot be null.", "null")]
        }

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_a_value_past_a_unique_column_s_range_never_reaches_the_uniqueness_query(
        self,
    ) -> None:
        # The constraint's check queries with the value, and SQLite's driver
        # raised OverflowError for it.
        book = Book.objects.create(
            author=Author.objects.create(name="Ada"), title="Notes", price=Decimal("1.00")
        )
        detail = _refusal(_EditionForm, {"book": book.pk, "number": 2**63})
        assert coded(detail) == {
            "number": [
                (
                    "Ensure this value is less than or equal to %s." % (2**63 - 1),
                    "max_value",
                )
            ]
        }

    @pytest.mark.django_db
    def test_a_value_past_the_column_s_stated_range_is_refused_in_the_same_words(self) -> None:
        # Where the backend states the range, the kernel reads that one.
        assert coded(_refusal(_Viewed, {"title": "Hi", "views": 2**63})) == {
            "views": [("Ensure this value is less than or equal to %s." % (2**63 - 1), "max_value")]
        }

    @pytest.mark.django_db
    def test_an_integer_on_a_column_that_is_no_integer_s_is_the_field_s(self) -> None:
        # A text column holds any integer's digits, so it has no range.
        cleaned = FormValidator(_Viewed).validate({"title": 2**63, "views": 1}, CONTEXT)
        assert cleaned == {"title": str(2**63), "views": 1}

    @pytest.mark.django_db
    def test_an_integer_field_no_column_holds_is_the_field_s(self) -> None:
        # A form field the model has no column for is no column's to range.
        form_class = type("Paged", (_Viewed,), {"pages": forms.IntegerField()})
        cleaned = FormValidator(form_class).validate(
            {"title": "Hi", "views": 1, "pages": 2**63}, CONTEXT
        )
        assert cleaned == {"title": "Hi", "views": 1, "pages": 2**63}

    @pytest.mark.django_db
    @pytest.mark.usefixtures("ranges")
    def test_a_value_clean_sets_for_a_column_the_form_does_not_edit_is_never_judged(
        self,
    ) -> None:
        # Django writes onto the instance only the columns the form edits, and
        # validates only those, so a value ``clean()`` sets for another is the
        # form's to use: Django's own validation takes it, and so does this.
        class Doubled(forms.ModelForm):
            factor = forms.IntegerField()

            class Meta:
                model = Post
                fields = ["title"]

            def clean(self) -> dict[str, Any]:
                cleaned = super().clean()
                cleaned["views"] = cleaned["factor"] * 2**62
                return cleaned

        data = {"title": "Hi", "factor": 4}
        own = Doubled(data=data)
        assert own.is_valid()
        assert FormValidator(Doubled).validate(data, CONTEXT) == own.cleaned_data

    @pytest.mark.django_db
    @pytest.mark.usefixtures("ranges")
    @pytest.mark.parametrize(
        "meta",
        [
            {"fields": ["title"]},
            {"exclude": ["body", "published", "views", "author", "tags"]},
        ],
        ids=["fields", "exclude"],
    )
    def test_a_field_declared_over_a_column_meta_leaves_out_is_never_judged(
        self, meta: dict[str, Any]
    ) -> None:
        # Declared on the form but left out by ``Meta``, the value is never
        # written onto the instance, and Django validates no column for it.
        form_class = type(
            "Undeclared",
            (forms.ModelForm,),
            {"views": forms.IntegerField(), "Meta": type("Meta", (), {"model": Post, **meta})},
        )
        data = {"title": "Hi", "views": 2**63}
        own = form_class(data=data)
        assert own.is_valid()
        assert FormValidator(form_class).validate(data, CONTEXT) == own.cleaned_data

    @pytest.mark.django_db
    def test_a_value_that_is_no_integer_is_left_to_the_field(self) -> None:
        assert coded(_refusal(_Viewed, {"title": "Hi", "views": "many"})) == {
            "views": [("Enter a whole number.", "invalid")]
        }

    @pytest.fixture(params=["stated", "unstated"])
    def ranges(self, request: pytest.FixtureRequest) -> None:
        """The range the backend states, and none, as Django 4.2's SQLite states."""
        if request.param == "unstated":
            request.getfixturevalue("unstated_ranges")

    @pytest.mark.django_db
    @pytest.mark.usefixtures("ranges")
    def test_a_clean_method_bringing_a_value_inside_the_range_is_taken(self) -> None:
        # The method runs on the value the field cleaned, as Django runs it,
        # and the column holds what it hands back.
        class Clamped(_EditionForm):
            def clean_number(self) -> int:
                return min(self.cleaned_data["number"], 10)

        book = Book.objects.create(
            author=Author.objects.create(name="Ada"), title="Notes", price=Decimal("1.00")
        )
        cleaned = FormValidator(Clamped).validate({"book": book.pk, "number": 2**63}, CONTEXT)
        assert cleaned["number"] == 10

    @pytest.mark.django_db
    @pytest.mark.usefixtures("ranges")
    def test_a_clean_method_s_own_refusal_answers_for_a_value_past_the_range(self) -> None:
        class Capped(_EditionForm):
            def clean_number(self) -> int:
                raise forms.ValidationError("Too many editions.", code="too_many")

        book = Book.objects.create(
            author=Author.objects.create(name="Ada"), title="Notes", price=Decimal("1.00")
        )
        detail = _refusal(Capped, {"book": book.pk, "number": 2**63})
        assert coded(detail) == {"number": [("Too many editions.", "too_many")]}

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_digits_a_text_field_cleans_to_are_held_to_the_column(self) -> None:
        # The model reads the digits as the integer they spell, and the
        # constraint's check queried with it.
        form_class = type("Spelled", (_EditionForm,), {"number": forms.CharField()})
        book = Book.objects.create(
            author=Author.objects.create(name="Ada"), title="Notes", price=Decimal("1.00")
        )
        detail = _refusal(form_class, {"book": book.pk, "number": str(2**63)})
        assert coded(detail) == {
            "number": [
                ("Ensure this value is less than or equal to %s." % (2**63 - 1), "max_value")
            ]
        }

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_text_the_column_reads_as_no_number_is_the_model_s(self) -> None:
        # Never compared with the range: the model refuses it in its words.
        form_class = _form_over_views(forms.CharField())
        assert coded(_refusal(form_class, {"title": "Hi", "views": "abc"})) == {
            "views": [("\u201cabc\u201d value must be an integer.", "invalid")]
        }

    @pytest.mark.django_db
    @pytest.mark.usefixtures("unstated_ranges")
    def test_the_values_at_either_end_of_the_column_s_range_are_taken(self) -> None:
        validator = FormValidator(_Viewed)
        for views in (-(2**63), 2**63 - 1):
            assert validator.validate({"title": "Hi", "views": views}, CONTEXT)["views"] == views


@pytest.mark.django_db
class TestModelForm:
    def test_an_update_excludes_the_target_from_the_uniqueness_check(self) -> None:
        ada = User.objects.create_user(username="ada")
        bob = User.objects.create_user(username="bob")
        taken = {"username": ["A user with that username already exists."]}
        validator = FormValidator(Username)

        assert validator.validate({"username": "ada"}, ValidationContext(ada, ada)) == {
            "username": "ada"
        }
        assert _refusal(Username, {"username": "ada"}, target=bob) == taken
        assert _refusal(Username, {"username": "ada"}) == taken

    def test_validating_leaves_the_target_as_it_was(self) -> None:
        ada = User.objects.create_user(username="ada")
        User.objects.create_user(username="bob")
        validator = FormValidator(Username)

        validator.validate({"username": "ada2"}, ValidationContext(ada, ada))
        assert ada.username == "ada"
        _refusal(Username, {"username": "bob"}, target=ada)
        assert ada.username == "ada"

    def test_an_update_helper_saves_what_the_form_cleaned(self) -> None:
        # The case the copy exists for: a helper that saves only what changed
        # would see no change on a target the form had already written to.
        ada = User.objects.create_user(username="ada")
        cleaned = FormValidator(Username).validate(
            {"username": "lovelace"}, ValidationContext(ada, ada)
        )

        result = update_from_input(ada, cleaned)

        assert [change.field for change in result.changes] == ["username"]
        ada.refresh_from_db()
        assert ada.username == "lovelace"

    def test_a_collection_target_binds_the_form_as_a_create(self) -> None:
        User.objects.create_user(username="ada")
        everyone = User.objects.all()
        validator = FormValidator(Username)

        assert validator.validate({"username": "carol"}, ValidationContext(None, everyone)) == {
            "username": "carol"
        }
        assert _refusal(Username, {"username": "ada"}, target=everyone) == {
            "username": ["A user with that username already exists."]
        }

    def test_a_model_forms_generated_fields_map_like_declared_ones(self) -> None:
        assert _declared(BookForm) == [
            ("author", "integer", None, None, None, True, False),
            ("title", "string", None, None, None, True, False),
            ("price", "string", "decimal", None, None, True, False),
            ("status", "string", None, None, ("draft", "published"), True, False),
        ]
        author = Author.objects.create(name="Ada")
        cleaned = FormValidator(BookForm).validate(
            {"author": author.pk, "title": "Notes", "price": "9.99", "status": "published"},
            CONTEXT,
        )
        assert cleaned == {
            "author": author,
            "title": "Notes",
            "price": Decimal("9.99"),
            "status": "published",
        }


def _labels(form_class: type[forms.BaseForm]) -> dict[str, Any]:
    return {p.name: p.choice_labels for p in FormValidator(form_class).parameters()}


class TestChoiceLabels:
    def test_every_choice_is_labelled_option_groups_flattened_and_the_empty_one_dropped(
        self,
    ) -> None:
        labels = _labels(Everything)
        assert labels["colour"] == (("red", "Red"), ("amber", "Amber"), ("blue", "Blue"))
        assert labels["size"] == ((1, "Small"), (2, "Large"))
        # An array's labels are its element's, beside its choices.
        assert labels["tags"] == (("a", "A"), ("b", "B"))
        assert labels["scores"] == ((1, "One"), (2, "Two"))
        # No choices, no labels: rows, and fields with no choices at all.
        assert labels["author"] is None
        assert labels["name"] is None

    def test_a_plain_choice_field_labels_the_strings_it_compares(self) -> None:
        form_class = _form("Rating", stars=forms.ChoiceField(choices=[(1, "One"), (2, "Two")]))
        assert _labels(form_class) == {"stars": (("1", "One"), ("2", "Two"))}

    def test_an_option_group_given_as_a_tuple_is_labelled_too(self) -> None:
        form_class = _form(
            "Shade",
            shade=forms.ChoiceField(choices=(("Warm", (("red", "Red"), ("amber", "Amber"))),)),
        )
        assert _labels(form_class) == {"shade": (("red", "Red"), ("amber", "Amber"))}

    def test_a_callable_choice_set_has_no_labels_either(self) -> None:
        form_class = _form("Paint", colour=forms.ChoiceField(choices=lambda: [("red", "Red")]))
        assert _labels(form_class) == {"colour": None}

    def test_a_label_stays_lazy_until_a_reader_renders_it(self) -> None:
        form_class = _form(
            "Poll",
            answer=forms.ChoiceField(choices=[("y", gettext_lazy("Yes")), ("n", "No")]),
        )
        ((_, label), _) = _labels(form_class)["answer"]
        with translation.override("fr"):
            assert str(label) == "Oui"
        assert str(label) == "Yes"

    def test_a_model_form_labels_the_model_field_s_choices(self) -> None:
        assert _labels(BookForm)["status"] == (("draft", "Draft"), ("published", "Published"))


class _Upload(forms.Form):
    title = forms.CharField()
    attachment = forms.FileField()
    cover = forms.ImageField(required=False)


class TestFiles:
    def test_a_file_field_declares_a_file(self) -> None:
        assert list(FormValidator(_Upload).parameters()) == [
            Parameter("title", "string", required=True),
            Parameter("attachment", "file", required=True),
            Parameter("cover", "file", nullable=True),
            # Its clear checkbox, which only an optional file offers.
            Parameter("cover-clear", "boolean"),
        ]

    def test_the_upload_is_read_from_the_call_s_arguments(self) -> None:
        upload = SimpleUploadedFile("notes.txt", b"hello")
        cleaned = FormValidator(_Upload).validate({"title": "Notes", "attachment": upload}, CONTEXT)
        assert cleaned == {"title": "Notes", "attachment": upload, "cover": None}

    def test_a_missing_required_upload_is_refused_in_the_form_s_words(self) -> None:
        assert _refusal(_Upload, {"title": "Notes"}) == {"attachment": [REQUIRED]}

    def test_a_file_with_no_name_is_the_form_s_to_refuse(self) -> None:
        # A ContentFile a Python caller builds without a name: the shape check
        # takes any Django File, and the form needs a name to read one.
        detail = _refusal(_Upload, {"title": "Notes", "attachment": ContentFile(b"hello")})
        assert detail == {"attachment": [forms.FileField.default_error_messages["invalid"]]}

    def test_the_shape_check_passes_the_upload_the_form_takes(self) -> None:
        upload = SimpleUploadedFile("notes.txt", b"hello")
        validator = FormValidator(_Upload)
        checked = check_arguments(validator.parameters(), {"title": "Notes", "attachment": upload})
        assert validator.validate(checked, CONTEXT)["attachment"] is upload


class _DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "attachment", "scan"]


class _BareUpload(forms.Form):
    # An optional file whose widget offers no clear checkbox.
    cover = forms.FileField(required=False, widget=forms.FileInput)


def _clashing(*, disabled: bool) -> type[forms.BaseForm]:
    """A form whose field is named as another field's clear checkbox.

    Only reachable through ``base_fields`` set by hand, since a class
    attribute cannot carry a hyphen.
    """
    return type(
        "_Clashing",
        (forms.BaseForm,),
        {
            "base_fields": {
                "cover": forms.FileField(required=False),
                "cover-clear": forms.BooleanField(required=False, disabled=disabled),
            }
        },
    )


@pytest.fixture
def media(settings: Any) -> Iterator[str]:
    """Default storage in a directory removed after the test, so no upload outlives it."""
    with tempfile.TemporaryDirectory() as root:
        settings.MEDIA_ROOT = root
        yield root


def _stored(title: str = "Notes") -> Document:
    """A saved row holding both files, in the test's media directory."""
    row = Document(title=title)
    row.attachment.save("notes.txt", ContentFile(b"notes"), save=False)
    row.scan.save("scan.txt", ContentFile(b"scan"), save=False)
    row.save()
    return row


def _row(target: Document) -> ValidationContext:
    return ValidationContext(None, target)


class TestClearingAFile:
    def test_a_custom_widget_with_no_clear_checkbox_offers_none(self) -> None:
        assert list(FormValidator(_BareUpload).parameters()) == [
            Parameter("cover", "file", nullable=True)
        ]

    def test_a_model_form_s_optional_file_offers_one_and_its_required_one_none(self) -> None:
        names = [parameter.name for parameter in FormValidator(_DocumentForm).parameters()]
        assert names == ["title", "attachment", "attachment-clear", "scan"]

    @pytest.mark.parametrize("disabled", [False, True], ids=["a-field", "a-disabled-field"])
    def test_a_field_named_as_a_clear_checkbox_is_refused(self, disabled: bool) -> None:
        # A disabled field is no parameter, and still reads the same data key.
        with pytest.raises(ImproperlyConfigured) as refused:
            FormValidator(_clashing(disabled=disabled))
        message = str(refused.value)
        assert "_Clashing.cover: its clear checkbox, 'cover-clear', is also the name" in message
        assert "rename the field" in message

    @pytest.mark.django_db
    def test_without_it_null_keeps_the_file_and_false_is_no_file(self, media: str) -> None:
        # Why the checkbox is declared: neither JSON value clears a file.
        row = _stored()
        validator = FormValidator(_DocumentForm)
        cleaned = validator.validate({"title": "Notes", "attachment": None}, _row(row))
        assert cleaned["attachment"] == row.attachment
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(validator.parameters(), {"title": "Notes", "attachment": False})
        assert refused.value.detail["attachment"] == ["Expected a file."]

    @pytest.mark.django_db
    def test_the_checkbox_clears_the_file_as_the_form_cleans_it(self, media: str) -> None:
        row = _stored()
        cleaned = FormValidator(_DocumentForm).validate(
            {"title": "Notes", "attachment-clear": True}, _row(row)
        )
        # The form's own value for a cleared file: False, under the field's
        # name, and nothing under the checkbox's.
        assert cleaned["attachment"] is False
        assert "attachment-clear" not in cleaned
        assert cleaned["scan"] == row.scan

    @pytest.mark.django_db
    def test_an_unchecked_box_keeps_the_file(self, media: str) -> None:
        row = _stored()
        cleaned = FormValidator(_DocumentForm).validate(
            {"title": "Notes", "attachment-clear": False}, _row(row)
        )
        assert cleaned["attachment"] == row.attachment

    @pytest.mark.django_db
    def test_an_upload_and_a_checked_box_together_are_refused_in_the_form_s_words(
        self, media: str
    ) -> None:
        upload = SimpleUploadedFile("new.txt", b"new")
        with pytest.raises(InvalidArguments) as refused:
            FormValidator(_DocumentForm).validate(
                {"title": "Notes", "attachment": upload, "attachment-clear": True}, _row(_stored())
            )
        contradiction = forms.FileField.default_error_messages["contradiction"]
        assert refused.value.detail == {"attachment": [contradiction]}

    @pytest.mark.django_db
    def test_a_partial_call_sending_only_the_checkbox_clears_the_file(self, media: str) -> None:
        row = _stored()
        cleaned = FormValidator(_DocumentForm).validate(
            {"attachment-clear": True}, ValidationContext(None, row, partial=True)
        )
        assert cleaned == {"attachment": False}

    @pytest.mark.django_db
    def test_a_partial_call_sending_the_box_unchecked_leaves_the_file_out(self, media: str) -> None:
        # Unchecked is what absent is on a whole call, so it is on a partial
        # one too: nothing about the file was sent.
        cleaned = FormValidator(_DocumentForm).validate(
            {"attachment-clear": False}, ValidationContext(None, _stored(), partial=True)
        )
        assert cleaned == {}

    @pytest.mark.django_db
    def test_dispatch_takes_the_checkbox_and_the_service_clears_the_row(self, media: str) -> None:
        def clear(instance: Document, attachment: Any) -> Document:
            # A ModelForm's own write: ``save_form_data`` stores a cleared
            # file as the empty name.
            Document._meta.get_field("attachment").save_form_data(instance, attachment)
            instance.save()
            return instance

        spec = ServiceSpec(
            service=clear,
            permissions=[Unrestricted()],
            validator=FormValidator(_DocumentForm),
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda pk: Document.objects.get(pk=pk),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
            ),
            partial=True,
        )
        row = _stored()
        dispatch(spec, principal=None, arguments={"pk": row.pk, "attachment-clear": True})
        row.refresh_from_db()
        assert row.attachment.name == ""
        assert row.scan.name.startswith("scans/")


class _Profile(forms.Form):
    title = forms.CharField()
    subscribed = forms.BooleanField(required=False)
    age = forms.IntegerField(required=False)
    nickname = forms.CharField(required=False)

    def clean_nickname(self) -> str:
        nickname = self.cleaned_data["nickname"]
        if nickname != nickname.lower():
            raise ValidationError("Lower case only.")
        return nickname

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        assert cleaned is not None
        # ``get``, as Django advises: a field that failed, or was not sent on a
        # partial call, has no cleaned value.
        if cleaned.get("title") == "admin":
            raise ValidationError("Reserved.")
        return cleaned


class _PermissionForm(forms.ModelForm):
    class Meta:
        model = Permission
        fields = ["name", "content_type", "codename"]


class _PermissionName(forms.ModelForm):
    class Meta:
        model = Permission
        fields = ["name", "codename"]


class _EditionForm(forms.ModelForm):
    class Meta:
        model = Edition
        fields = ["book", "number"]


def _a_pair_and_its_collision(pair: str) -> tuple[Any, Any, dict[str, Any]]:
    """A row holding a value, another row beside it, and the whole call that collides.

    ``(taken, target, whole)``: the value of the pair's second field the first
    row holds, the row an update targets, which shares the first field, and
    the whole call that would give the target the first row's pair.
    """
    if pair == "permission":
        kind = ContentType.objects.get_for_model(Book)
        Permission.objects.create(name="Taken", content_type=kind, codename="taken")
        target = Permission.objects.create(name="Mine", content_type=kind, codename="mine")
        whole = {"name": "Mine", "content_type": str(kind.pk), "codename": "taken"}
        return "taken", target, whole
    book = Book.objects.create(
        author=Author.objects.create(name="Ada"), title="Notes", price=Decimal("1.00")
    )
    Edition.objects.create(book=book, number=1)
    target = Edition.objects.create(book=book, number=2)
    return 1, target, {"book": str(book.pk), "number": 1}


def _partial(target: Any = None) -> ValidationContext:
    """A partial call's context, built per test so the module imports on any version."""
    return ValidationContext(None, target, partial=True)


class TestPartial:
    def test_a_partial_call_returns_only_the_fields_the_caller_sent(self) -> None:
        validator = FormValidator(_Profile)
        assert validator.validate({"age": 3}, _partial()) == {"age": 3}
        # The same call made whole is refused, and an absent checkbox cleans
        # to False there, which is exactly what a partial update must not write.
        assert _refusal(_Profile, {"age": 3}) == {"title": [REQUIRED]}
        assert validator.validate({"title": "Ada"}, CONTEXT) == {
            "title": "Ada",
            "subscribed": False,
            "age": None,
            "nickname": "",
        }

    def test_a_boolean_left_out_has_no_key_and_one_sent_false_keeps_it(self) -> None:
        validator = FormValidator(_Profile)
        assert validator.validate({"title": "Ada"}, _partial()) == {"title": "Ada"}
        assert validator.validate({"subscribed": False}, _partial()) == {"subscribed": False}

    def test_a_value_sent_is_checked_as_on_a_whole_call(self) -> None:
        # Under partial a required field may be left out, never sent empty: a
        # null for it is refused as before, rather than cleaned to a blank.
        assert _refusal_partial(_Profile, {"title": None}) == {"title": [REQUIRED]}
        assert _refusal_partial(_Profile, {"nickname": "Ada"}) == {"nickname": ["Lower case only."]}
        assert _refusal_partial(_Profile, {"title": "admin"}) == {"non_field_errors": ["Reserved."]}

    def test_a_field_left_out_is_not_cleaned_at_all(self) -> None:
        # Bound with every field and only made optional, the empty nickname
        # would pass through clean_nickname; one whose rule refuses a blank
        # would refuse a call that never named the field.
        class Strict(_Profile):
            def clean_title(self) -> str:
                title = self.cleaned_data["title"]
                if not title:
                    raise ValidationError("A title cannot be blank.")
                return title

        assert FormValidator(Strict).validate({"age": 1}, _partial()) == {"age": 1}

    def test_parameters_still_say_what_a_whole_call_needs(self) -> None:
        validator = FormValidator(_Profile)
        validator.validate({"age": 3}, _partial())
        required = {p.name: p.required for p in validator.parameters()}
        assert required == {"title": True, "subscribed": False, "age": False, "nickname": False}
        # And the next whole call still requires the title.
        assert _refusal(_Profile, {"age": 3}) == {"title": [REQUIRED]}

    @pytest.mark.django_db
    def test_a_partial_model_form_update_keeps_what_the_caller_left_out(self) -> None:
        author = Author.objects.create(name="Ada")
        book = Book.objects.create(author=author, title="Notes", price=Decimal("9.99"))
        validator = FormValidator(BookForm)

        cleaned = validator.validate({"price": "5.00"}, ValidationContext(None, book, partial=True))

        assert cleaned == {"price": Decimal("5.00")}
        result = update_from_input(book, cleaned)
        assert [change.field for change in result.changes] == ["price"]
        book.refresh_from_db()
        assert (book.title, book.price, book.author) == ("Notes", Decimal("5.00"), author)

    @pytest.mark.django_db
    def test_a_partial_model_form_update_checks_uniqueness_on_what_was_sent(self) -> None:
        ada = User.objects.create_user(username="ada")
        User.objects.create_user(username="bob")
        validator = FormValidator(Username)
        context = ValidationContext(ada, ada, partial=True)

        assert validator.validate({}, context) == {}
        with pytest.raises(InvalidArguments) as caught:
            validator.validate({"username": "bob"}, context)
        assert caught.value.detail == {"username": ["A user with that username already exists."]}

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("form_class", "pair"),
        [
            # ``unique_together``, which a ModelForm checks with validate_unique.
            pytest.param(_PermissionForm, "permission", id="unique-together"),
            # A ``UniqueConstraint``, which it checks with validate_constraints.
            pytest.param(_EditionForm, "edition", id="unique-constraint"),
        ],
    )
    def test_a_partial_update_colliding_with_a_unique_pair_is_refused_as_a_whole_one_is(
        self, form_class: type[forms.ModelForm], pair: str
    ) -> None:
        # The update sends one field of the pair. Bound with only that field,
        # the form excluded the other from its uniqueness check, and so skipped
        # the pair: the collision surfaced as an IntegrityError on save.
        taken, target, whole = _a_pair_and_its_collision(pair)
        sent = {"codename": taken} if pair == "permission" else {"number": taken}
        refused = _refusal(form_class, whole, target)
        assert list(refused) == ["non_field_errors"]
        with pytest.raises(InvalidArguments) as caught:
            FormValidator(form_class).validate(sent, ValidationContext(None, target, partial=True))
        assert caught.value.detail == refused

    @pytest.mark.django_db
    def test_a_whole_model_form_call_checks_uniqueness_once(
        self, django_assert_num_queries: Any
    ) -> None:
        ada = User.objects.create_user(username="ada")
        with django_assert_num_queries(1):
            FormValidator(Username).validate({"username": "carol"}, ValidationContext(ada, ada))

    @pytest.mark.django_db
    def test_a_partial_call_with_no_target_row_checks_nothing_it_was_not_sent(self) -> None:
        # Bound as a create, the form's instance holds the model's defaults for
        # every field not sent, which nothing will write: checked, an empty
        # username that a row already holds refused a call that never sent one.
        User.objects.create(username="")
        context = ValidationContext(None, None, partial=True)
        assert FormValidator(Username).validate({}, context) == {}

    @pytest.mark.django_db
    def test_a_partial_update_checks_no_pair_the_form_does_not_declare(self) -> None:
        # The whole call of a form without ``content_type`` excludes the pair,
        # as Django excludes any model field a form does not have, and a
        # partial one is no stricter.
        taken, target, _ = _a_pair_and_its_collision("permission")
        context = ValidationContext(None, target, partial=True)
        assert FormValidator(_PermissionName).validate({"codename": taken}, context) == {
            "codename": taken
        }

    @pytest.mark.django_db
    def test_a_partial_update_that_collides_with_nothing_passes(self) -> None:
        _, target, _ = _a_pair_and_its_collision("permission")
        context = ValidationContext(None, target, partial=True)
        assert FormValidator(_PermissionForm).validate({"codename": "free"}, context) == {
            "codename": "free"
        }

    def test_the_whole_and_validated_paths_agree(self) -> None:
        validated = FormValidator(_Profile).validated({"age": 3}, _partial())
        assert (validated.values, validated.data, dict(validated.pool)) == (
            {"age": 3},
            {"age": 3},
            {},
        )


def _refusal_partial(form_class: type[forms.BaseForm], arguments: dict[str, Any]) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        FormValidator(form_class).validate(arguments, _partial())
    return caught.value.detail


class _CodedForm(forms.Form):
    title = forms.CharField(max_length=3)
    count = forms.IntegerField(required=False)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        # One message with a code of its own and one with none, which DRF
        # reports as ``invalid``.
        if cleaned.get("count") == 13:
            raise ValidationError(["Unlucky.", ValidationError("Taken.", code="taken")])
        return cleaned


class TestRefusalCodes:
    """Django's own code on each message, which ``form.errors`` read as strings drops."""

    def test_a_field_s_refusal_keeps_its_code(self) -> None:
        assert coded(_refusal(_CodedForm, {"count": "x"})) == {
            "title": [("This field is required.", "required")],
            "count": [("Enter a whole number.", "invalid")],
        }

    def test_a_rendered_message_keeps_its_code(self) -> None:
        # ``max_length``'s message is rendered from its params, as Django renders it.
        assert coded(_refusal(_CodedForm, {"title": "long"})) == {
            "title": [
                ("Ensure this value has at most 3 characters (it has 4).", "max_length"),
            ]
        }

    def test_a_form_wide_refusal_keeps_its_code_or_says_invalid(self) -> None:
        assert coded(_refusal(_CodedForm, {"title": "ok", "count": 13})) == {
            "non_field_errors": [("Unlucky.", "invalid"), ("Taken.", "taken")]
        }

    @pytest.mark.django_db
    def test_a_unique_pair_s_refusal_keeps_django_s_code_whole_and_partial(self) -> None:
        taken, target, whole = _a_pair_and_its_collision("edition")
        refused = coded(_refusal(_EditionForm, whole, target))
        with pytest.raises(InvalidArguments) as caught:
            FormValidator(_EditionForm).validate(
                {"number": taken}, ValidationContext(None, target, partial=True)
            )
        assert coded(caught.value.detail) == refused
        assert [code for _, code in refused["non_field_errors"]] == ["unique_together"]
