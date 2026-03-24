from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import cache_page

from .forms import (
    ImportVoyantCSVForm,
    TranslationCorrectionForm,
    TranslationFinalizeForm,
    TranslationReviewForm,
    TranslatorApplicationForm,
)
from .models import Locale, LocaleAssignment, StringUnit, Translation, TranslatorApplication
from .permissions import (
    is_approver as _is_approver,
    is_approved_reviewer as _is_approved_reviewer,
    is_approved_translator as _is_approved_translator,
    is_superadmin as _is_superadmin,
)


YORUBA_LOCALE_CODE = "yo"
QUEUE_PAGE_SIZE = 50


# ── Public pages ──────────────────────────────────────────────────────────────

def home(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/home.html")


def about(request: HttpRequest) -> HttpResponse:
    return render(request, "l10n/about.html")


def workflow(request: HttpRequest) -> HttpResponse:
    """Visual walkthrough of the AI-assisted translation pipeline."""
    return render(request, "l10n/workflow.html")


@cache_page(60 * 10)
def progress(request: HttpRequest) -> HttpResponse:
    """Public per-language translation progress tracker."""
    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    # Single aggregated query instead of 4-5 queries per locale
    stats_qs = (
        Translation.objects.filter(locale__enabled=True)
        .values("locale_id")
        .annotate(
            approved=Count(
                "id",
                filter=Q(approved_text__isnull=False) & ~Q(approved_text=""),
            ),
            in_review=Count(
                "id", filter=Q(status=Translation.TranslationStatus.IN_REVIEW)
            ),
            qa_warnings=Count("id", filter=~Q(qa_flags=[])),
            ai_translated=Count(
                "id",
                filter=Q(machine_draft__isnull=False) & ~Q(machine_draft=""),
            ),
            machine_draft_count=Count(
                "id", filter=Q(status=Translation.TranslationStatus.MACHINE_DRAFT)
            ),
        )
    )
    stats_by_locale = {row["locale_id"]: row for row in stats_qs}

    locale_stats = []
    total_approved = 0
    total_needs_review = 0
    total_ai_translated = 0
    for locale in locales:
        row = stats_by_locale.get(locale.id, {})
        approved = row.get("approved", 0)
        in_review = row.get("in_review", 0)
        machine_draft = row.get("machine_draft_count", 0)
        qa_warnings = row.get("qa_warnings", 0)
        ai_translated = row.get("ai_translated", 0)
        pct = round((approved / total_strings * 100) if total_strings else 0, 1)
        draft_pct = round(((approved + machine_draft + in_review) / total_strings * 100) if total_strings else 0, 1)

        total_approved += approved
        total_needs_review += machine_draft
        total_ai_translated += ai_translated

        locale_stats.append(
            {
                "locale": locale,
                "approved": approved,
                "in_review": in_review,
                "machine_draft": machine_draft,
                "ai_translated": ai_translated,
                "qa_warnings": qa_warnings,
                "total": total_strings,
                "pct": pct,
                "draft_pct": draft_pct,
                "missing": max(total_strings - approved - machine_draft - in_review, 0),
            }
        )

    return render(
        request,
        "l10n/progress.html",
        {
            "locale_stats": locale_stats,
            "total_strings": total_strings,
            "total_approved": total_approved,
            "total_needs_review": total_needs_review,
            "total_ai_translated": total_ai_translated,
        },
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


def _get_user_locale(user, request=None):
    """Return the locale for the user, or None.

    Superadmins without an application can pick a locale via ?locale= query param.
    """
    # Try application locale first
    try:
        app = user.translator_application
        return app.desired_locale
    except Exception:
        pass
    # Superadmins can pick any enabled locale
    if _is_superadmin(user) and request:
        locale_code = (request.GET.get("locale") or "").strip().lower()
        if locale_code:
            return Locale.objects.filter(code=locale_code, enabled=True).first()
        # Fall back to first enabled locale
        return Locale.objects.filter(enabled=True).order_by("name").first()
    return None


@login_required
def review_queue(request: HttpRequest) -> HttpResponse:
    if not _is_approved_reviewer(request.user):
        return redirect("l10n_application")

    locale = _get_user_locale(request.user, request)
    if not locale:
        return redirect("l10n_application")

    # Non-superadmins need a locale assignment.
    if not _is_superadmin(request.user):
        if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
            return redirect("l10n_application")

    locales = Locale.objects.filter(enabled=True).order_by("name") if _is_superadmin(request.user) else None

    translations_qs = _review_queue_qs(locale)

    paginator = Paginator(translations_qs, QUEUE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_query = f"locale={locale.code}" if locales else ""

    return render(
        request,
        "l10n/review_list.html",
        {"translations": page_obj, "page_obj": page_obj, "page_query": page_query, "locale": locale, "locales": locales},
    )


def _review_queue_qs(locale):
    """Return the base queryset for the review queue (same ordering as review_queue view)."""
    return (
        Translation.objects.filter(locale=locale)
        .exclude(machine_draft__isnull=True)
        .exclude(machine_draft="")
        .filter(approved_text__isnull=True)
        .filter(status=Translation.TranslationStatus.MACHINE_DRAFT)
        .select_related("string_unit")
        .order_by("string_unit__location", "string_unit__message_id")
    )


@login_required
def review_detail(request: HttpRequest, translation_id: int) -> HttpResponse:
    if not _is_approved_reviewer(request.user):
        return redirect("l10n_application")

    tr = get_object_or_404(Translation.objects.select_related("string_unit", "locale"), pk=translation_id)

    # Superadmins can review any locale; regular reviewers only their assigned locale.
    if not _is_superadmin(request.user):
        locale = _get_user_locale(request.user)
        if not locale or tr.locale_id != locale.id:
            return redirect("l10n_review")
        if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
            return redirect("l10n_application")

    # Compute prev/next in the review queue for this locale
    queue_ids = list(
        _review_queue_qs(tr.locale).values_list("id", flat=True)
    )
    try:
        idx = queue_ids.index(tr.id)
    except ValueError:
        idx = -1
    prev_id = queue_ids[idx - 1] if idx > 0 else None
    next_id = queue_ids[idx + 1] if 0 <= idx < len(queue_ids) - 1 else None
    queue_position = idx + 1 if idx >= 0 else None
    queue_total = len(queue_ids)

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
            # After saving, go to the next item in queue (or back to queue if none left)
            if next_id:
                return redirect("l10n_review_detail", translation_id=next_id)
            return redirect("l10n_review")
    else:
        form = TranslationReviewForm(instance=tr)

    return render(request, "l10n/review_detail.html", {
        "tr": tr,
        "form": form,
        "prev_id": prev_id,
        "next_id": next_id,
        "queue_position": queue_position,
        "queue_total": queue_total,
    })


@login_required
def translator_queue(request: HttpRequest) -> HttpResponse:
    if not _is_approved_translator(request.user):
        return redirect("l10n_application")

    locale = _get_user_locale(request.user, request)
    if not locale:
        return redirect("l10n_application")

    if not _is_superadmin(request.user):
        if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
            return redirect("l10n_application")

    locales = Locale.objects.filter(enabled=True).order_by("name") if _is_superadmin(request.user) else None

    translations_qs = (
        Translation.objects.filter(locale=locale)
        .exclude(machine_draft__isnull=True)
        .exclude(machine_draft="")
        .filter(approved_text__isnull=True)
        .filter(status=Translation.TranslationStatus.REJECTED)
        .select_related("string_unit")
        .order_by("string_unit__location", "string_unit__message_id")
    )

    paginator = Paginator(translations_qs, QUEUE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_query = f"locale={locale.code}" if locales else ""

    return render(
        request,
        "l10n/translator_list.html",
        {"translations": page_obj, "page_obj": page_obj, "page_query": page_query, "locale": locale, "locales": locales},
    )


@login_required
def translator_detail(request: HttpRequest, translation_id: int) -> HttpResponse:
    if not _is_approved_translator(request.user):
        return redirect("l10n_application")

    tr = get_object_or_404(Translation.objects.select_related("string_unit", "locale"), pk=translation_id)

    if not _is_superadmin(request.user):
        locale = _get_user_locale(request.user)
        if not locale or tr.locale_id != locale.id:
            return redirect("l10n_translate")
        if not LocaleAssignment.objects.filter(user=request.user, locale=locale).exists():
            return redirect("l10n_application")

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
        if getattr(request.user, "is_superuser", False):
            # Superadmins can approve machine drafts directly without a prior review step.
            status_filter = models.Q(status=Translation.TranslationStatus.IN_REVIEW) | models.Q(
                status=Translation.TranslationStatus.MACHINE_DRAFT
            )
        else:
            status_filter = models.Q(status=Translation.TranslationStatus.IN_REVIEW)

        translations = (
            Translation.objects.filter(locale=selected_locale)
            .filter(status_filter)
            .filter(approved_text__isnull=True)
            .exclude(machine_draft__isnull=True)
            .exclude(machine_draft="")
            .select_related("string_unit")
            .order_by("string_unit__location", "string_unit__message_id")
        )

    paginator = Paginator(translations, QUEUE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_query = f"locale={selected_locale.code}" if selected_locale else ""

    return render(
        request,
        "l10n/approver_list.html",
        {
            "translations": page_obj,
            "page_obj": page_obj,
            "page_query": page_query,
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
            candidate = (
                (tr.translator_text or "").strip()
                or (tr.reviewer_text or "").strip()
                or (tr.machine_draft or "").strip()
            )
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
@cache_page(60 * 5)
def dashboard(request: HttpRequest) -> HttpResponse:
    """Multi-locale staff dashboard with per-language progress stats."""
    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    # Single aggregated query instead of 4-5 queries per locale
    stats_qs = (
        Translation.objects.filter(locale__enabled=True)
        .values("locale_id")
        .annotate(
            approved=Count(
                "id",
                filter=Q(approved_text__isnull=False) & ~Q(approved_text=""),
            ),
            qa_warnings=Count("id", filter=~Q(qa_flags=[])),
            stale=Count(
                "id", filter=Q(status=Translation.TranslationStatus.STALE)
            ),
            in_review=Count(
                "id", filter=Q(status=Translation.TranslationStatus.IN_REVIEW)
            ),
        )
    )
    stats_by_locale = {row["locale_id"]: row for row in stats_qs}

    locale_stats = []
    for locale in locales:
        row = stats_by_locale.get(locale.id, {})
        approved = row.get("approved", 0)
        pct = round((approved / total_strings * 100) if total_strings else 0, 1)

        locale_stats.append(
            {
                "locale": locale,
                "approved": approved,
                "missing": max(total_strings - approved, 0),
                "qa_warnings": row.get("qa_warnings", 0),
                "stale": row.get("stale", 0),
                "in_review": row.get("in_review", 0),
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
@cache_page(60 * 5)
def ai_progress_dashboard(request: HttpRequest) -> HttpResponse:
    """Staff-only dashboard focused on AI draft coverage."""

    locales = Locale.objects.filter(enabled=True).order_by("name")
    total_strings = StringUnit.objects.count()

    # Single aggregated query instead of 5 queries per locale
    stats_qs = (
        Translation.objects.filter(locale__enabled=True)
        .values("locale_id")
        .annotate(
            drafted=Count(
                "id",
                filter=Q(machine_draft__isnull=False) & ~Q(machine_draft=""),
            ),
            approved=Count(
                "id",
                filter=Q(approved_text__isnull=False) & ~Q(approved_text=""),
            ),
            in_review=Count(
                "id", filter=Q(status=Translation.TranslationStatus.IN_REVIEW)
            ),
            rejected=Count(
                "id", filter=Q(status=Translation.TranslationStatus.REJECTED)
            ),
            flagged=Count(
                "id", filter=Q(status=Translation.TranslationStatus.FLAGGED)
            ),
        )
    )
    stats_by_locale = {row["locale_id"]: row for row in stats_qs}

    locale_stats = []
    for locale in locales:
        row = stats_by_locale.get(locale.id, {})
        drafted = row.get("drafted", 0)
        pct = round((drafted / total_strings * 100) if total_strings else 0, 1)
        locale_stats.append(
            {
                "locale": locale,
                "drafted": drafted,
                "approved": row.get("approved", 0),
                "in_review": row.get("in_review", 0),
                "rejected": row.get("rejected", 0),
                "flagged": row.get("flagged", 0),
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
