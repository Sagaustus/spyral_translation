import pytest

from l10n.models import Locale, StringUnit, Translation
from l10n.services.qa import compute_qa_flags


@pytest.mark.django_db
def test_missing_placeholder_flag():
    flags = compute_qa_flags(source="Hello {0}", target="Bonjour")
    assert any(f["code"] == "missing_placeholder" for f in flags)
    missing = next(f for f in flags if f["code"] == "missing_placeholder")["details"]["missing"]
    assert "{0}" in missing


@pytest.mark.django_db
def test_html_tag_mismatch_flag():
    flags = compute_qa_flags(source="<b>Hi</b>", target="<b>Salut")
    assert any(f["code"] == "html_tag_mismatch" for f in flags)


@pytest.mark.django_db
def test_unbalanced_braces_flag():
    flags = compute_qa_flags(source="X", target="{")
    assert any(f["code"] == "unbalanced_braces" for f in flags)


@pytest.mark.django_db
def test_saving_translation_updates_qa_flags():
    locale = Locale.objects.create(code="fr", bcp47="fr", name="French")
    su = StringUnit.objects.create(location="ui", message_id="hello", source_text="Hello {0}")

    t = Translation.objects.create(string_unit=su, locale=locale, reviewer_text="Bonjour")
    t.refresh_from_db()

    assert any(f["code"] == "missing_placeholder" for f in t.qa_flags)


@pytest.mark.django_db
def test_empty_translation_only_warns_on_approve():
    locale = Locale.objects.create(code="es", bcp47="es", name="Spanish")
    su = StringUnit.objects.create(location="ui", message_id="bye", source_text="Bye")

    t = Translation.objects.create(string_unit=su, locale=locale)
    t.refresh_from_db()
    assert not any(f["code"] == "empty_translation" for f in t.qa_flags)

    t.status = Translation.TranslationStatus.APPROVED
    t.save(update_fields=["status"])
    t.refresh_from_db()
    assert any(f["code"] == "empty_translation" for f in t.qa_flags)
