from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.utils import translation
from django.utils.translation import gettext_lazy

from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Author, Book
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
                forms.FileField(),
                "Upload.field: a FileField takes an uploaded file, which no JSON "
                "transport carries.",
            ),
            (
                forms.ImageField(),
                "Upload.field: a ImageField takes an uploaded file, which no JSON "
                "transport carries.",
            ),
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
        assert all(type(m) is str for messages in detail.values() for m in messages)

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
