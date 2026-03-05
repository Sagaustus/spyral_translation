from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from l10n.models import Locale, LocaleAssignment, StringUnit, Translation, TranslatorApplication

@pytest.mark.django_db
def test_dashboard_requires_staff(client):
    url = reverse("l10n_dashboard")
    resp = client.get(url)
    assert resp.status_code in {302, 301}

    User = get_user_model()
    user = User.objects.create_user(username="staff", password="pw", is_staff=True)
    client.force_login(user)

    resp2 = client.get(url)
    assert resp2.status_code == 200


@pytest.mark.django_db
def test_import_page_requires_staff(client):
    url = reverse("l10n_import_voyant_csv")
    resp = client.get(url)
    assert resp.status_code in {302, 301}


@pytest.mark.django_db
def test_export_requires_staff(client):
    url = reverse("l10n_export_yo_csv")
    resp = client.get(url)
    assert resp.status_code in {302, 301}

    User = get_user_model()
    user = User.objects.create_user(username="staff2", password="pw", is_staff=True)
    client.force_login(user)

    resp2 = client.get(url)
    assert resp2.status_code == 200
    assert resp2.headers.get("Content-Type", "").startswith("text/csv")


@pytest.mark.django_db
def test_import_dry_run_upload_works(client):
    User = get_user_model()
    user = User.objects.create_user(username="staff3", password="pw", is_staff=True)
    client.force_login(user)

    csv_content = "Location,ID,en,est,yo\nui,hello,Hello,2024-01-01,\n"
    uploaded = SimpleUploadedFile(
        "voyant.csv", csv_content.encode("utf-8"), content_type="text/csv"
    )

    url = reverse("l10n_import_voyant_csv")
    resp = client.post(url, data={"csv_file": uploaded, "dry_run": "on"})
    assert resp.status_code == 200
    # Page renders output in a <pre>.
    assert "Import summary" in resp.content.decode("utf-8")


@pytest.mark.django_db
def test_public_pages_render(client):
    for name in [
        "l10n_home",
        "l10n_about",
        "l10n_team",
        "l10n_call_translators",
        "l10n_login",
    ]:
        resp = client.get(reverse(name))
        assert resp.status_code == 200


@pytest.mark.django_db
def test_application_signup_creates_user_and_pending_application(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)

    resp = client.post(
        reverse("l10n_apply"),
        data={
            "username": "applicant1",
            "email": "a@example.com",
            "password": "S3curePassword!",
            "password_confirm": "S3curePassword!",
            "full_name": "Applicant One",
            "affiliation": "Example University",
            "desired_locale": str(yo.id),
            "wants_acknowledgement": "on",
            "acknowledgement_name": "Applicant One",
        },
        follow=True,
    )

    assert resp.status_code == 200
    User = get_user_model()
    user = User.objects.get(username="applicant1")
    app = TranslatorApplication.objects.get(user=user)
    assert app.status == TranslatorApplication.ApplicationStatus.PENDING
    assert app.desired_locale_id == yo.id


@pytest.mark.django_db
def test_review_is_blocked_until_superadmin_approves(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    unit = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello")
    Translation.objects.create(
        string_unit=unit,
        locale=yo,
        machine_draft="Pẹlẹ o",
        approved_text=None,
        status=Translation.TranslationStatus.MACHINE_DRAFT,
        provenance=Translation.TranslationProvenance.MT,
    )

    User = get_user_model()
    user = User.objects.create_user(username="applicant2", password="pw")
    TranslatorApplication.objects.create(
        user=user,
        full_name="Applicant Two",
        affiliation="",
        desired_locale=yo,
        status=TranslatorApplication.ApplicationStatus.PENDING,
    )

    client.force_login(user)
    resp = client.get(reverse("l10n_review"), follow=True)
    assert resp.status_code == 200
    assert "My Application" in resp.content.decode("utf-8")

    # Approve (simulate superadmin action): mark approved, add reviewer group, assign locale.
    reviewer_group, _ = Group.objects.get_or_create(name="L10N_REVIEWER")
    reviewer_group.user_set.add(user)
    LocaleAssignment.objects.create(user=user, locale=yo)
    app = TranslatorApplication.objects.get(user=user)
    app.status = TranslatorApplication.ApplicationStatus.APPROVED
    app.save()

    resp2 = client.get(reverse("l10n_review"))
    assert resp2.status_code == 200
    assert "Review Queue" in resp2.content.decode("utf-8")
