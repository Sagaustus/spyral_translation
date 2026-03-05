from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render

from .forms import ImportVoyantCSVForm, TranslationReviewForm, TranslatorApplicationForm
from .models import Locale, LocaleAssignment, StringUnit, Translation, TranslatorApplication


YORUBA_LOCALE_CODE = "yo"


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/home.html")


def about(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/about.html")


def team(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/team.html")


def call_translators(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/call_translators.html")


def apply(request: HttpRequest) -> HttpResponse:
    _ensure_yoruba_locale()

    if request.method == "POST":
        form = TranslatorApplicationForm(request.POST)
        if form.is_valid():
            application = form.save()
            login(request, application.user)
            return redirect("l10n_application")
    else:
        form = TranslatorApplicationForm()

    return render(request, "l10n/apply.html", {"form": form})


@login_required
def application_status(request: HttpRequest) -> HttpResponse:
    application = None
    try:
        application = request.user.translator_application
    except Exception:
        application = None

    return render(request, "l10n/application_status.html", {"application": application})


def _is_approved_reviewer(user) -> bool:
    if not user.is_authenticated:
        return False
    try:
        app = user.translator_application
    except Exception:
        return False
    if app.status != TranslatorApplication.ApplicationStatus.APPROVED:
        return False
    return user.groups.filter(name="L10N_REVIEWER").exists()


@login_required
def review_queue(request: HttpRequest) -> HttpResponse:
    if not _is_approved_reviewer(request.user):
        return redirect("l10n_application")

    app = request.user.translator_application
    locale = app.desired_locale

    # Only allow review if a superadmin has assigned the locale.
    if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
        return redirect("l10n_application")

    translations = (
        Translation.objects.filter(locale=locale)
        .exclude(machine_draft__isnull=True)
        .exclude(machine_draft="")
        .filter(approved_text__isnull=True)
        .select_related("string_unit")
        .order_by("string_unit__location", "string_unit__message_id")
        [:200]
    )

    return render(
        request,
        "l10n/review_list.html",
        {"translations": translations, "locale": locale},
    )


@login_required
def review_detail(request: HttpRequest, translation_id: int) -> HttpResponse:
    if not _is_approved_reviewer(request.user):
        return redirect("l10n_application")

    app = request.user.translator_application
    locale = app.desired_locale

    if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
        return redirect("l10n_application")

    tr = get_object_or_404(Translation.objects.select_related("string_unit", "locale"), pk=translation_id)
    if tr.locale_id != locale.id:
        return redirect("l10n_review")

    if request.method == "POST":
        form = TranslationReviewForm(request.POST, instance=tr)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.reviewer = request.user
            updated.save(update_fields=["reviewer", "reviewer_text", "status", "qa_flags", "updated_at"])
            return redirect("l10n_review")
    else:
        form = TranslationReviewForm(instance=tr)

    return render(request, "l10n/review_detail.html", {"tr": tr, "form": form})


def _ensure_yoruba_locale() -> Locale:
    locale, _created = Locale.objects.get_or_create(
        code=YORUBA_LOCALE_CODE,
        defaults={
            "bcp47": "yo",
            "name": "Yoruba",
            "script": "Latn",
            "is_rtl": False,
            "enabled": True,
        },
    )
    return locale


@staff_member_required
def dashboard(request: HttpRequest) -> HttpResponse:
    yo = _ensure_yoruba_locale()

    total_string_units = StringUnit.objects.count()
    approved_count = Translation.objects.filter(
        locale=yo,
        approved_text__isnull=False,
    ).exclude(approved_text="").count()
    missing_count = max(total_string_units - approved_count, 0)

    qa_warning_count = Translation.objects.filter(locale=yo).exclude(qa_flags=[]).count()
    stale_count = Translation.objects.filter(
        locale=yo,
        status=Translation.TranslationStatus.STALE,
    ).count()

    return render(
        request,
        "l10n/dashboard.html",
        {
            "total_string_units": total_string_units,
            "approved_count": approved_count,
            "missing_count": missing_count,
            "qa_warning_count": qa_warning_count,
            "stale_count": stale_count,
        },
    )


@staff_member_required
def import_voyant_csv(request: HttpRequest) -> HttpResponse:
    output = ""
    error = ""

    if request.method == "POST":
        form = ImportVoyantCSVForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["csv_file"]
            dry_run = bool(form.cleaned_data.get("dry_run"))

            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    for chunk in uploaded.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name

                buf = io.StringIO()
                call_command(
                    "import_voyant_csv",
                    path=tmp_path,
                    dry_run=dry_run,
                    stdout=buf,
                )
                output = buf.getvalue().strip()
            except Exception as exc:  # pragma: no cover
                error = str(exc)
            finally:
                if tmp_path:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except OSError:
                        pass
    else:
        form = ImportVoyantCSVForm()

    return render(
        request,
        "l10n/import_voyant_csv.html",
        {"form": form, "output": output, "error": error},
    )


@staff_member_required
def export_yo_csv(_request: HttpRequest) -> HttpResponse:
    _ensure_yoruba_locale()

    # Generate the CSV in-memory. This avoids Windows file-lock issues when a
    # temporary file is still held open by the response while the temp dir is
    # being cleaned up.
    header = [
        "location",
        "message_id",
        "source_en",
        "target_locale",
        "translation",
        "status",
        "source_hash",
        "translation_updated_at",
        "source_updated_on",
    ]

    locale = Locale.objects.get(code=YORUBA_LOCALE_CODE)

    translations_by_string_unit_id: dict[int, dict[str, object]] = {}
    for row in (
        Translation.objects.filter(locale=locale)
        .values("string_unit_id", "approved_text", "updated_at")
        .iterator()
    ):
        translations_by_string_unit_id[int(row["string_unit_id"])] = row

    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(header)

    for su in (
        StringUnit.objects.all()
        .order_by("location", "message_id")
        .only(
            "id",
            "location",
            "message_id",
            "source_text",
            "source_hash",
            "source_updated_on",
        )
        .iterator()
    ):
        tr_row = translations_by_string_unit_id.get(su.id)
        approved_text = None
        updated_at = None
        if tr_row:
            approved_text = tr_row.get("approved_text")  # type: ignore[assignment]
            updated_at = tr_row.get("updated_at")

        approved = (approved_text or "").strip() if approved_text is not None else ""
        if approved:
            status = "APPROVED"
            translation_value = approved
            translation_updated_at = updated_at.isoformat() if updated_at else ""
        else:
            status = "MISSING"
            translation_value = ""
            translation_updated_at = ""

        writer.writerow(
            [
                su.location,
                su.message_id,
                su.source_text,
                YORUBA_LOCALE_CODE,
                translation_value,
                status,
                su.source_hash,
                translation_updated_at,
                su.source_updated_on,
            ]
        )

    csv_bytes = out.getvalue().encode("utf-8")
    filename = f"voyant_{YORUBA_LOCALE_CODE}.csv"

    response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
