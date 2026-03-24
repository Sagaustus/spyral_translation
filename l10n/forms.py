from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Locale, Translation, TranslatorApplication


class ImportVoyantCSVForm(forms.Form):
    csv_file = forms.FileField(required=True)
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        help_text="If checked, parse and report changes without writing to the DB.",
    )


def _country_choices() -> list[tuple[str, str]]:
    try:
        import pycountry
    except Exception:
        return [("", "(Select)")]

    choices = [("", "(Select)")]
    for c in sorted(pycountry.countries, key=lambda x: x.name):
        code = getattr(c, "alpha_2", "")
        if not code:
            continue
        choices.append((code, c.name))
    return choices


def _language_choices() -> list[tuple[str, str]]:
    try:
        import pycountry
    except Exception:
        return [("", "(Select)")]

    choices = [("", "(Select)")]
    seen: set[str] = set()
    for l in pycountry.languages:
        code = getattr(l, "alpha_3", None) or getattr(l, "alpha_2", None)
        name = getattr(l, "name", None)
        if not code or not name:
            continue
        if code in seen:
            continue
        seen.add(code)
        choices.append((str(code), str(name)))
    choices.sort(key=lambda x: x[1])
    return choices


class TranslatorApplicationForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput)

    full_name = forms.CharField(max_length=200)
    affiliation = forms.CharField(max_length=255, required=False)

    desired_locale = forms.ModelChoiceField(queryset=Locale.objects.filter(enabled=True).order_by("code"))

    current_country = forms.ChoiceField(choices=_country_choices(), required=False)
    home_country = forms.ChoiceField(choices=_country_choices(), required=False)

    first_language = forms.ChoiceField(choices=_language_choices(), required=False)
    second_language = forms.ChoiceField(choices=_language_choices(), required=False)
    dialect = forms.CharField(max_length=100, required=False)

    wants_acknowledgement = forms.BooleanField(required=False, initial=True)
    acknowledgement_name = forms.CharField(max_length=200, required=False)

    desired_role = forms.ChoiceField(
        choices=TranslatorApplication.DesiredRole.choices,
        initial=TranslatorApplication.DesiredRole.REVIEWER,
    )

    photo = forms.ImageField(required=False)

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise ValidationError("Username is required.")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise ValidationError("That username is already taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password") or ""
        pw2 = cleaned.get("password_confirm") or ""
        if pw and pw2 and pw != pw2:
            self.add_error("password_confirm", "Passwords do not match.")
        if pw:
            try:
                validate_password(pw)
            except ValidationError as exc:
                self.add_error("password", exc)

        wants_ack = bool(cleaned.get("wants_acknowledgement"))
        ack_name = (cleaned.get("acknowledgement_name") or "").strip()
        if wants_ack and not ack_name:
            # Default acknowledgement name to full name if left blank.
            cleaned["acknowledgement_name"] = (cleaned.get("full_name") or "").strip()
        return cleaned

    def save(self) -> TranslatorApplication:
        if not self.is_valid():
            raise ValidationError("Form must be valid before saving.")

        User = get_user_model()
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data.get("email") or "",
            password=self.cleaned_data["password"],
        )

        application = TranslatorApplication.objects.create(
            user=user,
            full_name=self.cleaned_data["full_name"],
            affiliation=self.cleaned_data.get("affiliation") or "",
            desired_locale=self.cleaned_data["desired_locale"],
            current_country=self.cleaned_data.get("current_country") or "",
            home_country=self.cleaned_data.get("home_country") or "",
            first_language=self.cleaned_data.get("first_language") or "",
            second_language=self.cleaned_data.get("second_language") or "",
            dialect=self.cleaned_data.get("dialect") or "",
            wants_acknowledgement=bool(self.cleaned_data.get("wants_acknowledgement")),
            acknowledgement_name=(self.cleaned_data.get("acknowledgement_name") or "").strip(),
            photo=self.cleaned_data.get("photo"),
            desired_role=self.cleaned_data.get("desired_role", TranslatorApplication.DesiredRole.REVIEWER),
            status=TranslatorApplication.ApplicationStatus.PENDING,
        )
        return application


class TranslationReviewForm(forms.ModelForm):
    class Meta:
        model = Translation
        fields = ["reviewer_text", "status"]

    status = forms.ChoiceField(
        choices=[
            (Translation.TranslationStatus.IN_REVIEW, "Approve (send to approver)"),
            (Translation.TranslationStatus.REJECTED, "Disapprove (send to translator)"),
            (Translation.TranslationStatus.FLAGGED, "Flag (needs attention)"),
        ]
    )


class TranslationCorrectionForm(forms.ModelForm):
    class Meta:
        model = Translation
        fields = ["translator_text"]


class TranslationFinalizeForm(forms.ModelForm):
    class Meta:
        model = Translation
        fields = ["approved_text"]
