from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from l10n.models import Locale, LocaleAssignment, StringUnit, Translation, TranslatorApplication


@pytest.mark.django_db
def test_reviewer_review_sends_to_approver_without_finalizing(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    unit = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello")
    tr = Translation.objects.create(
        string_unit=unit,
        locale=yo,
        machine_draft="Pẹlẹ o",
        approved_text=None,
        status=Translation.TranslationStatus.MACHINE_DRAFT,
        provenance=Translation.TranslationProvenance.MT,
    )

    User = get_user_model()
    reviewer = User.objects.create_user(username="reviewer_role", password="pw")
    TranslatorApplication.objects.create(
        user=reviewer,
        full_name="Reviewer",
        affiliation="",
        desired_locale=yo,
        status=TranslatorApplication.ApplicationStatus.APPROVED,
    )

    Group.objects.get_or_create(name="L10N_REVIEWER")[0].user_set.add(reviewer)
    LocaleAssignment.objects.create(user=reviewer, locale=yo)

    client.force_login(reviewer)
    resp = client.post(
        reverse("l10n_review_detail", args=[tr.id]),
        data={
            "reviewer_text": "Pẹlẹ o",
            "status": Translation.TranslationStatus.IN_REVIEW,
        },
        follow=True,
    )

    assert resp.status_code == 200
    tr.refresh_from_db()
    assert tr.status == Translation.TranslationStatus.IN_REVIEW
    assert (tr.reviewer_text or "").strip() == "Pẹlẹ o"
    assert tr.approved_text is None


@pytest.mark.django_db
def test_translator_correction_sets_translator_text_and_moves_to_in_review(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    unit = StringUnit.objects.create(location="ui", message_id="bye", source_text="Bye")
    tr = Translation.objects.create(
        string_unit=unit,
        locale=yo,
        machine_draft="O dabo",
        reviewer_text="Needs better tone",
        status=Translation.TranslationStatus.REJECTED,
        provenance=Translation.TranslationProvenance.MT,
    )

    User = get_user_model()
    translator = User.objects.create_user(username="translator_role", password="pw")
    TranslatorApplication.objects.create(
        user=translator,
        full_name="Translator",
        affiliation="",
        desired_locale=yo,
        status=TranslatorApplication.ApplicationStatus.APPROVED,
    )

    Group.objects.get_or_create(name="L10N_TRANSLATOR")[0].user_set.add(translator)
    LocaleAssignment.objects.create(user=translator, locale=yo)

    client.force_login(translator)
    resp = client.post(
        reverse("l10n_translate_detail", args=[tr.id]),
        data={"translator_text": "Ó dàbọ̀"},
        follow=True,
    )
    assert resp.status_code == 200

    tr.refresh_from_db()
    assert tr.status == Translation.TranslationStatus.IN_REVIEW
    assert (tr.translator_text or "").strip() == "Ó dàbọ̀"
    assert tr.translator_id == translator.id
    assert tr.approved_text is None


@pytest.mark.django_db
def test_approver_finalizes_and_sets_approved_fields(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    unit = StringUnit.objects.create(location="ui", message_id="thanks", source_text="Thanks")
    tr = Translation.objects.create(
        string_unit=unit,
        locale=yo,
        machine_draft="E se",
        translator_text="Ẹ ṣé",
        status=Translation.TranslationStatus.IN_REVIEW,
        provenance=Translation.TranslationProvenance.HUMAN,
    )

    User = get_user_model()
    approver = User.objects.create_user(username="approver_role", password="pw")
    Group.objects.get_or_create(name="L10N_APPROVER")[0].user_set.add(approver)
    LocaleAssignment.objects.create(user=approver, locale=yo)

    client.force_login(approver)
    resp = client.post(
        reverse("l10n_approve_detail", args=[tr.id]),
        data={"approved_text": "Ẹ ṣé"},
        follow=True,
    )
    assert resp.status_code == 200

    tr.refresh_from_db()
    assert tr.status == Translation.TranslationStatus.APPROVED
    assert (tr.approved_text or "").strip() == "Ẹ ṣé"
    assert tr.approved_by_id == approver.id
    assert tr.approved_at is not None
    assert tr.source_hash_at_last_update == unit.source_hash


@pytest.mark.django_db
def test_approver_queue_includes_translator_only_items(client):
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    unit = StringUnit.objects.create(location="ui", message_id="ok", source_text="OK")
    Translation.objects.create(
        string_unit=unit,
        locale=yo,
        machine_draft="O dara",
        reviewer_text="",
        translator_text="Ó dára",
        status=Translation.TranslationStatus.IN_REVIEW,
        provenance=Translation.TranslationProvenance.HUMAN,
    )

    User = get_user_model()
    approver = User.objects.create_user(username="approver_role2", password="pw")
    Group.objects.get_or_create(name="L10N_APPROVER")[0].user_set.add(approver)
    LocaleAssignment.objects.create(user=approver, locale=yo)

    client.force_login(approver)
    resp = client.get(reverse("l10n_approve"), data={"locale": "yo"})
    assert resp.status_code == 200
    assert "Approver Queue" in resp.content.decode("utf-8")
