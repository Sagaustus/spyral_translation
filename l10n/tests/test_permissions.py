from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from l10n.admin import TranslationAdmin, approve_selected
from l10n.models import Locale, LocaleAssignment, StringUnit, Translation


@pytest.mark.django_db
def test_reviewer_queryset_is_locale_scoped():
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French")
    de = Locale.objects.create(code="de", bcp47="de", name="German")

    unit = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello")
    Translation.objects.create(string_unit=unit, locale=fr)
    Translation.objects.create(string_unit=unit, locale=de)

    reviewer = get_user_model().objects.create_user(
        username="reviewer",
        password="pw",
    )
    Group.objects.get_or_create(name="L10N_REVIEWER")[0].user_set.add(reviewer)
    LocaleAssignment.objects.create(user=reviewer, locale=fr)

    rf = RequestFactory()
    request = rf.get("/admin/")
    request.user = reviewer

    ma = TranslationAdmin(Translation, admin.site)
    qs = ma.get_queryset(request)

    assert set(qs.values_list("locale__code", flat=True)) == {"fr"}


@pytest.mark.django_db
def test_reviewer_readonly_fields_block_approved_text():
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French")
    unit = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello")
    tr = Translation.objects.create(string_unit=unit, locale=fr)

    reviewer = get_user_model().objects.create_user(
        username="reviewer2",
        password="pw",
    )
    Group.objects.get_or_create(name="L10N_REVIEWER")[0].user_set.add(reviewer)
    LocaleAssignment.objects.create(user=reviewer, locale=fr)

    rf = RequestFactory()
    request = rf.get("/admin/")
    request.user = reviewer

    ma = TranslationAdmin(Translation, admin.site)
    readonly = set(ma.get_readonly_fields(request, obj=tr))

    assert "approved_text" in readonly
    assert "machine_draft" in readonly
    assert "provenance" in readonly
    assert "locale" in readonly


@pytest.mark.django_db
def test_superadmin_can_approve_selected_and_reviewer_cannot(client):
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French")
    unit = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello")
    tr = Translation.objects.create(
        string_unit=unit,
        locale=fr,
        reviewer_text="Bonjour",
        approved_text="",
        provenance=Translation.TranslationProvenance.HUMAN,
        status=Translation.TranslationStatus.IN_REVIEW,
    )

    User = get_user_model()
    reviewer = User.objects.create_user(username="r3", password="pw")
    Group.objects.get_or_create(name="L10N_REVIEWER")[0].user_set.add(reviewer)
    LocaleAssignment.objects.create(user=reviewer, locale=fr)

    rf = RequestFactory()

    # Reviewer cannot approve (no changes)
    req_reviewer = rf.post("/admin/")
    req_reviewer.user = reviewer
    req_reviewer.session = client.session
    setattr(req_reviewer, "_messages", FallbackStorage(req_reviewer))

    approve_selected(None, req_reviewer, Translation.objects.filter(pk=tr.pk))
    tr.refresh_from_db()
    assert tr.status != Translation.TranslationStatus.APPROVED

    # Superadmin can approve
    superadmin = User.objects.create_user(username="sa", password="pw", is_superuser=True)

    req_sa = rf.post("/admin/")
    req_sa.user = superadmin
    req_sa.session = client.session
    setattr(req_sa, "_messages", FallbackStorage(req_sa))

    approve_selected(None, req_sa, Translation.objects.filter(pk=tr.pk))
    tr.refresh_from_db()

    assert tr.status == Translation.TranslationStatus.APPROVED
    assert tr.approved_text == "Bonjour"
    assert tr.source_hash_at_last_update == unit.source_hash
