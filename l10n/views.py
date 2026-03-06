from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.utils import timezone

from .forms import (
    ImportVoyantCSVForm,
    TranslationCorrectionForm,
    TranslationFinalizeForm,
    TranslationReviewForm,
    TranslatorApplicationForm,
)
from .models import Locale, LocaleAssignment, StringUnit, Translation, TranslatorApplication


YORUBA_LOCALE_CODE = "yo"


# ── Public pages ──────────────────────────────────────────────────────────────

def home(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/home.html")


def about(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/about.html")


def workflow(request: HttpRequest) -> HttpResponse:
    """Visual walkthrough of the AI-assisted translation pipeline."""
    return render(request, "l10n/workflow.html")


def progress(request: HttpRequest) -> HttpResponse:
    """Public per-language translation progress tracker."""
    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    locale_stats = []
    for locale in locales:
        approved = (
            Translation.objects.filter(locale=locale, approved_text__isnull=False)
            .exclude(approved_text="")
            .count()
        )
        in_review = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.IN_REVIEW
        ).count()
        machine_draft = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.MACHINE_DRAFT
        ).count()
        qa_warnings = Translation.objects.filter(locale=locale).exclude(qa_flags=[]).count()
        pct = round((approved / total_strings * 100) if total_strings else 0, 1)

        locale_stats.append(
            {
                "locale": locale,
                "approved": approved,
                "in_review": in_review,
                "machine_draft": machine_draft,
                "qa_warnings": qa_warnings,
                "total": total_strings,
                "pct": pct,
            }
        )

    return render(
        request,
        "l10n/progress.html",
        {"locale_stats": locale_stats, "total_strings": total_strings},
    )


def team(request: HttpRequest) -> HttpResponse:
    approved = (
        TranslatorApplication.objects.filter(status=TranslatorApplication.ApplicationStatus.APPROVED)
        .select_related("user", "desired_locale")
        .order_by("full_name")
    )
    return render(request, "l10n/team.html", {"approved_applications": approved})


def call_translators(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/call_translators.html")


def apply(request: HttpRequest) -> HttpResponse:
    _ensure_yoruba_locale()

    if request.method == "POST":
        form = TranslatorApplicationForm(request.POST, request.FILES)
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


def _is_approved_translator(user) -> bool:
    if not user.is_authenticated:
        return False
    try:
        app = user.translator_application
    except Exception:
        return False
    if app.status != TranslatorApplication.ApplicationStatus.APPROVED:
        return False
    return user.groups.filter(name="L10N_TRANSLATOR").exists()


def _is_approver(user) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=["L10N_APPROVER", "L10N_SUPERADMIN"]).exists()


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
        .filter(status=Translation.TranslationStatus.MACHINE_DRAFT)
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

            # Reviewer never finalizes approval. Final approval is done by an approver.
            # If reviewer sends back to translator/flagged, keep it unapproved.
            updated.approved_text = None

            updated.save(
                update_fields=[
                    "reviewer",
                    "reviewer_text",
                    "status",
                    "approved_text",
                    "provenance",
                    "qa_flags",
                    "updated_at",
                ]
            )
            return redirect("l10n_review")
    else:
        form = TranslationReviewForm(instance=tr)

    return render(request, "l10n/review_detail.html", {"tr": tr, "form": form})


@login_required
def translator_queue(request: HttpRequest) -> HttpResponse:
    if not _is_approved_translator(request.user):
        return redirect("l10n_application")

    app = request.user.translator_application
    locale = app.desired_locale

    if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
        return redirect("l10n_application")

    translations = (
        Translation.objects.filter(locale=locale)
        .exclude(machine_draft__isnull=True)
        .exclude(machine_draft="")
        .filter(approved_text__isnull=True)
        .filter(status=Translation.TranslationStatus.REJECTED)
        .select_related("string_unit")
        .order_by("string_unit__location", "string_unit__message_id")
        [:200]
    )

    return render(
        request,
        "l10n/translator_list.html",
        {"translations": translations, "locale": locale},
    )


@login_required
def translator_detail(request: HttpRequest, translation_id: int) -> HttpResponse:
    if not _is_approved_translator(request.user):
        return redirect("l10n_application")

    app = request.user.translator_application
    locale = app.desired_locale

    if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
        return redirect("l10n_application")

    tr = get_object_or_404(Translation.objects.select_related("string_unit", "locale"), pk=translation_id)
    if tr.locale_id != locale.id:
        return redirect("l10n_translate")

    if request.method == "POST":
        form = TranslationCorrectionForm(request.POST, instance=tr)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.translator = request.user
            updated.status = Translation.TranslationStatus.IN_REVIEW
            updated.approved_text = None
            updated.save(
                update_fields=[
                    "translator",
                    "translator_text",
                    "status",
                    "approved_text",
                    "qa_flags",
                    "updated_at",
                ]
            )
            return redirect("l10n_translate")
    else:
        form = TranslationCorrectionForm(instance=tr)

    return render(request, "l10n/translator_detail.html", {"tr": tr, "form": form})


@login_required
def approver_queue(request: HttpRequest) -> HttpResponse:
    if not _is_approver(request.user):
        return redirect("l10n_home")

    assigned_locale_ids = list(
        LocaleAssignment.objects.filter(user=request.user).values_list("locale_id", flat=True)
    )
    locales = Locale.objects.filter(enabled=True)
    if not getattr(request.user, "is_superuser", False):
        locales = locales.filter(id__in=assigned_locale_ids)
    locales = locales.order_by("name")

    locale_code = (request.GET.get("locale") or "").strip().lower()
    selected_locale = None
    if locale_code:
        selected_locale = locales.filter(code=locale_code).first()
    if selected_locale is None:
        selected_locale = locales.first()

    translations = Translation.objects.none()
    if selected_locale:
        translations = (
            Translation.objects.filter(locale=selected_locale)
            .filter(status=Translation.TranslationStatus.IN_REVIEW)
            .filter(approved_text__isnull=True)
            .exclude(
                (models.Q(reviewer_text__isnull=True) | models.Q(reviewer_text=""))
                & (models.Q(translator_text__isnull=True) | models.Q(translator_text=""))
            )
            .select_related("string_unit")
            .order_by("string_unit__location", "string_unit__message_id")
            [:200]
        )

    return render(
        request,
        "l10n/approver_list.html",
        {
            "translations": translations,
            "locales": locales,
            "selected_locale": selected_locale,
        },
    )


@login_required
def approver_detail(request: HttpRequest, translation_id: int) -> HttpResponse:
    if not _is_approver(request.user):
        return redirect("l10n_home")

    tr = get_object_or_404(Translation.objects.select_related("string_unit", "locale"), pk=translation_id)

    if not getattr(request.user, "is_superuser", False):
        if not LocaleAssignment.objects.filter(user=request.user, locale=tr.locale).exists():
            return redirect("l10n_approve")

    if request.method == "POST":
        form = TranslationFinalizeForm(request.POST, instance=tr)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.status = Translation.TranslationStatus.APPROVED
            updated.approved_by = request.user
            updated.approved_at = timezone.now()
            if updated.provenance != Translation.TranslationProvenance.IMPORTED:
                updated.provenance = Translation.TranslationProvenance.HUMAN
            updated.source_hash_at_last_update = updated.string_unit.source_hash
            updated.save(
                update_fields=[
                    "approved_text",
                    "status",
                    "approved_by",
                    "approved_at",
                    "provenance",
                    "source_hash_at_last_update",
                    "qa_flags",
                    "updated_at",
                ]
            )
            return redirect("l10n_approve")
    else:
        initial = {}
        if not (tr.approved_text or "").strip():
            candidate = (tr.translator_text or "").strip() or (tr.reviewer_text or "").strip()
            if candidate:
                initial["approved_text"] = candidate
        form = TranslationFinalizeForm(instance=tr, initial=initial)

    return render(request, "l10n/approver_detail.html", {"tr": tr, "form": form})


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
    """Multi-locale staff dashboard with per-language progress stats."""
    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    locale_stats = []
    for locale in locales:
        approved = (
            Translation.objects.filter(locale=locale, approved_text__isnull=False)
            .exclude(approved_text="")
            .count()
        )
        missing = max(total_strings - approved, 0)
        qa_warnings = Translation.objects.filter(locale=locale).exclude(qa_flags=[]).count()
        stale = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.STALE
        ).count()
        in_review = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.IN_REVIEW
        ).count()
        pct = round((approved / total_strings * 100) if total_strings else 0, 1)

        locale_stats.append(
            {
                "locale": locale,
                "approved": approved,
                "missing": missing,
                "qa_warnings": qa_warnings,
                "stale": stale,
                "in_review": in_review,
                "pct": pct,
            }
        )

    pending_applications = TranslatorApplication.objects.filter(
        status=TranslatorApplication.ApplicationStatus.PENDING,
    ).select_related("user", "desired_locale").order_by("-created_at")

    return render(
        request,
        "l10n/dashboard.html",
        {
            "total_strings": total_strings,
            "locale_stats": locale_stats,
            "locale_count": len(locale_stats),
            "pending_applications": pending_applications,
        },
    )


@staff_member_required
def ai_progress_dashboard(request: HttpRequest) -> HttpResponse:
    """Staff-only dashboard focused on AI draft coverage."""

    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    locale_stats = []
    for locale in locales:
        has_draft = (
            Translation.objects.filter(locale=locale)
            .exclude(machine_draft__isnull=True)
            .exclude(machine_draft="")
            .count()
        )
        approved = (
            Translation.objects.filter(locale=locale, approved_text__isnull=False)
            .exclude(approved_text="")
            .count()
        )
        in_review = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.IN_REVIEW
        ).count()
        rejected = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.REJECTED
        ).count()
        flagged = Translation.objects.filter(
            locale=locale, status=Translation.TranslationStatus.FLAGGED
        ).count()

        pct = round((has_draft / total_strings * 100) if total_strings else 0, 1)
        locale_stats.append(
            {
                "locale": locale,
                "drafted": has_draft,
                "approved": approved,
                "in_review": in_review,
                "rejected": rejected,
                "flagged": flagged,
                "total": total_strings,
                "pct": pct,
            }
        )

    return render(
        request,
        "l10n/ai_progress.html",
        {"locale_stats": locale_stats, "total_strings": total_strings},
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


def _build_locale_csv(locale: Locale) -> bytes:
    """Return a UTF-8 CSV of all string units and their approved translations for *locale*."""
    header = [
        "location", "message_id", "source_en", "target_locale",
        "translation", "status", "source_hash", "translation_updated_at", "source_updated_on",
    ]

    translations_by_su: dict[int, dict] = {}
    for row in (
        Translation.objects.filter(locale=locale)
        .values("string_unit_id", "approved_text", "updated_at")
        .iterator()
    ):
        translations_by_su[int(row["string_unit_id"])] = row

    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(header)

    for su in (
        StringUnit.objects.all()
        .order_by("location", "message_id")
        .only("id", "location", "message_id", "source_text", "source_hash", "source_updated_on")
        .iterator()
    ):
        tr_row = translations_by_su.get(su.id)
        approved_text = tr_row.get("approved_text") if tr_row else None
        updated_at = tr_row.get("updated_at") if tr_row else None
        approved = (approved_text or "").strip() if approved_text is not None else ""

        writer.writerow([
            su.location, su.message_id, su.source_text, locale.code,
            approved if approved else "",
            "APPROVED" if approved else "MISSING",
            su.source_hash,
            updated_at.isoformat() if (approved and updated_at) else "",
            su.source_updated_on,
        ])

    return out.getvalue().encode("utf-8")


@staff_member_required
def export_yo_csv(_request: HttpRequest) -> HttpResponse:
    """Legacy Yoruba-specific export kept for backwards compatibility."""
    _ensure_yoruba_locale()
    locale = Locale.objects.get(code=YORUBA_LOCALE_CODE)
    csv_bytes = _build_locale_csv(locale)
    response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="voyant_{YORUBA_LOCALE_CODE}.csv"'
    return response


@staff_member_required
def export_locale_csv(request: HttpRequest, locale_code: str) -> HttpResponse:
    """Export approved translations for any enabled locale as a CSV download."""
    locale = get_object_or_404(Locale, code=locale_code, enabled=True)
    csv_bytes = _build_locale_csv(locale)
    response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="voyant_{locale_code}.csv"'
    return response


# ── AI Pipeline trigger ────────────────────────────────────────────────────────

@staff_member_required
def trigger_pipeline(request: HttpRequest) -> HttpResponse:
    """Staff-only view: run the AI translation pipeline for a chosen locale.

    POST parameters
    ---------------
    locale_code : str   — target locale (must exist in DB)
    engine      : str   — "nllb" | "openai" | "ollama"
    limit       : int   — max strings to translate this run (safety cap)
    force       : bool  — re-translate strings that already have a draft
    no_score    : bool  — skip back-translation + similarity scoring
    """
    from django.conf import settings as dj_settings

    locales = Locale.objects.filter(enabled=True).order_by("name")
    default_limit = getattr(dj_settings, "PIPELINE_WEB_LIMIT", 30)
    default_engine = getattr(dj_settings, "TRANSLATION_ENGINE", "nllb")

    result: dict = {}

    if request.method == "POST":
        locale_code = (request.POST.get("locale_code") or "").strip().lower()
        engine = (request.POST.get("engine") or default_engine).strip().lower()
        try:
            limit = int(request.POST.get("limit") or default_limit)
        except (ValueError, TypeError):
            limit = default_limit

        force = request.POST.get("force") == "1"
        no_score = request.POST.get("no_score") == "1"

        if not locale_code:
            result["error"] = "Please select a locale."
        elif locale_code not in {loc.code for loc in locales}:
            result["error"] = f"Locale '{locale_code}' not found."
        else:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                call_command(
                    "run_pipeline",
                    locale=locale_code,
                    engine=engine,
                    limit=limit,
                    force=force,
                    no_score=no_score,
                    dry_run=False,
                    verbosity=1,
                    stdout=stdout_buf,
                    stderr=stderr_buf,
                )
                result["output"] = stdout_buf.getvalue()
                result["errors"] = stderr_buf.getvalue()
                result["locale_code"] = locale_code
                result["engine"] = engine
                result["limit"] = limit
            except Exception as exc:  # noqa: BLE001
                result["error"] = str(exc)

    return render(
        request,
        "l10n/pipeline_trigger.html",
        {
            "locales": locales,
            "default_engine": default_engine,
            "default_limit": default_limit,
            "result": result,
        },
    )
