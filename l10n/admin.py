import json

from django.contrib import admin, messages
from django.db import models
from django.db.models import QuerySet
from django.forms import Textarea

from .models import Locale, LocaleAssignment, StringUnit, Translation


def _truncate(value: str | None, length: int = 80) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= length:
        return value
    return value[: length - 1] + "…"


class TranslationInline(admin.TabularInline):
    model = Translation
    extra = 0
    show_change_link = True

    fields = ("locale", "status", "provenance", "short_translation", "updated_at")
    readonly_fields = fields
    can_delete = False

    @admin.display(description="Approved")
    def short_translation(self, obj: Translation) -> str:
        return _truncate(obj.approved_text)


@admin.register(Locale)
class LocaleAdmin(admin.ModelAdmin):
    list_display = ("code", "bcp47", "name", "script", "is_rtl", "enabled", "legacy_column")
    list_filter = ("enabled", "is_rtl", "script")
    search_fields = ("code", "bcp47", "name", "legacy_column")
    ordering = ("code",)


@admin.register(StringUnit)
class StringUnitAdmin(admin.ModelAdmin):
    list_display = (
        "location",
        "message_id",
        "short_source_text",
        "source_hash",
        "source_updated_on",
    )
    search_fields = ("location", "message_id", "source_text")
    ordering = ("location", "message_id")
    inlines = (TranslationInline,)

    @admin.display(description="Source", ordering="source_text")
    def short_source_text(self, obj: StringUnit) -> str:
        return _truncate(obj.source_text)


@admin.register(LocaleAssignment)
class LocaleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "locale", "created_at")
    list_filter = ("locale",)
    search_fields = (
        "user__username",
        "user__email",
        "locale__code",
        "locale__name",
    )
    autocomplete_fields = ("user", "locale")
    ordering = ("locale__code", "user__username")


def _is_in_group(user, group_name: str) -> bool:
    return user.groups.filter(name=group_name).exists()


def _is_superadmin(user) -> bool:
    return user.is_superuser or _is_in_group(user, "L10N_SUPERADMIN")


def _is_reviewer(user) -> bool:
    return _is_in_group(user, "L10N_REVIEWER")


def _assigned_locale_ids(user) -> list[int]:
    return list(LocaleAssignment.objects.filter(user=user).values_list("locale_id", flat=True))


class HasQAWarningsFilter(admin.SimpleListFilter):
    title = "QA warnings"
    parameter_name = "has_qa_warnings"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Has warnings"),
            ("no", "No warnings"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.exclude(qa_flags=[]).exclude(qa_flags__isnull=True)
        if value == "no":
            return queryset.filter(models.Q(qa_flags=[]) | models.Q(qa_flags__isnull=True))
        return queryset


@admin.action(description="Mark as In Review")
def mark_in_review(_modeladmin, _request, queryset):
    """Set status=IN_REVIEW for selected translations."""

    queryset.update(status=Translation.TranslationStatus.IN_REVIEW)


@admin.action(description="Flag selected")
def flag_selected(_modeladmin, _request, queryset):
    """Set status=FLAGGED for selected translations."""

    queryset.update(status=Translation.TranslationStatus.FLAGGED)


@admin.action(description="Approve selected")
def approve_selected(_modeladmin, request, queryset):
    """Safely approve translations.

    Rules:
    - Only superusers or members of group "L10N_SUPERADMIN" can execute.
    - If approved_text empty and reviewer_text non-empty, copy reviewer_text -> approved_text.
    - Always set status=APPROVED.
    - If provenance is not IMPORTED, set provenance=HUMAN.
    - Update source_hash_at_last_update from the StringUnit source_hash.
    """

    if not _is_superadmin(request.user):
        messages.error(request, "You do not have permission to approve translations.")
        return

    updated = 0
    for translation in queryset.select_related("string_unit"):
        changed = False

        if (
            not (translation.approved_text or "").strip()
            and (translation.reviewer_text or "").strip()
        ):
            translation.approved_text = translation.reviewer_text
            changed = True

        if translation.status != Translation.TranslationStatus.APPROVED:
            translation.status = Translation.TranslationStatus.APPROVED
            changed = True

        if translation.provenance != Translation.TranslationProvenance.IMPORTED:
            translation.provenance = Translation.TranslationProvenance.HUMAN
            changed = True

        new_hash = translation.string_unit.source_hash
        if translation.source_hash_at_last_update != new_hash:
            translation.source_hash_at_last_update = new_hash
            changed = True

        if changed:
            translation.save(
                update_fields=[
                    "approved_text",
                    "status",
                    "provenance",
                    "source_hash_at_last_update",
                    "updated_at",
                ]
            )
            updated += 1

    messages.success(request, f"Approved {updated} translation(s).")


@admin.register(Translation)
class TranslationAdmin(admin.ModelAdmin):
    list_display = (
        "locale",
        "location",
        "message_id",
        "short_source",
        "has_qa_warnings",
        "status",
        "provenance",
        "has_machine_draft",
        "updated_at",
    )
    list_filter = (HasQAWarningsFilter, "locale", "status", "provenance")
    search_fields = (
        "string_unit__location",
        "string_unit__message_id",
        "string_unit__source_text",
        "approved_text",
        "reviewer_text",
        "machine_draft",
    )
    ordering = ("locale", "string_unit__location", "string_unit__message_id")
    list_select_related = ("locale", "string_unit", "reviewer")
    autocomplete_fields = ("locale", "string_unit", "reviewer")

    readonly_fields = (
        "display_location",
        "display_message_id",
        "display_source_text",
        "display_source_hash",
        "source_hash_at_last_update",
        "qa_warnings",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Key",
            {
                "fields": (
                    "locale",
                    "display_location",
                    "display_message_id",
                )
            },
        ),
        (
            "Source (English)",
            {
                "fields": (
                    "display_source_text",
                    "display_source_hash",
                )
            },
        ),
        (
            "Translations",
            {"fields": ("machine_draft", "reviewer_text", "approved_text")},
        ),
        (
            "QA Warnings",
            {"fields": ("qa_warnings",)},
        ),
        (
            "Workflow",
            {"fields": ("status", "provenance", "reviewer")},
        ),
        (
            "Metadata",
            {"fields": ("source_hash_at_last_update", "created_at", "updated_at")},
        ),
    )

    actions = (mark_in_review, approve_selected, flag_selected)

    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 6, "cols": 100})},
    }

    def get_queryset(self, request):
        qs: QuerySet[Translation] = super().get_queryset(request)

        if _is_superadmin(request.user):
            return qs
        if _is_reviewer(request.user):
            locale_ids = _assigned_locale_ids(request.user)
            return qs.filter(locale_id__in=locale_ids)
        return qs.none()

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return super().has_change_permission(request, obj=obj)

        if _is_superadmin(request.user):
            return super().has_change_permission(request, obj=obj)

        if _is_reviewer(request.user):
            locale_ids = _assigned_locale_ids(request.user)
            return obj.locale_id in locale_ids

        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj=obj))

        if _is_superadmin(request.user):
            return readonly

        if _is_reviewer(request.user):
            # Reviewers may only edit reviewer_text and status (not APPROVED).
            reviewer_readonly = {
                "approved_text",
                "provenance",
                "machine_draft",
                "locale",
                "string_unit",
                "source_hash_at_last_update",
                "reviewer",
            }
            for field in reviewer_readonly:
                if field not in readonly:
                    readonly.append(field)

        return readonly

    def save_model(self, request, obj, form, change):
        if _is_reviewer(request.user) and not _is_superadmin(request.user):
            obj.reviewer = request.user

            # Prevent privilege escalation via crafted POSTs.
            if change and obj.pk:
                existing = Translation.objects.select_related("locale", "string_unit").get(
                    pk=obj.pk
                )
                obj.approved_text = existing.approved_text
                obj.machine_draft = existing.machine_draft
                obj.provenance = existing.provenance
                obj.locale = existing.locale
                obj.string_unit = existing.string_unit
                obj.source_hash_at_last_update = existing.source_hash_at_last_update

            if obj.status == Translation.TranslationStatus.APPROVED:
                obj.status = Translation.TranslationStatus.IN_REVIEW
                messages.warning(
                    request,
                    "Reviewers cannot set status=APPROVED. Set to IN_REVIEW instead.",
                )

        super().save_model(request, obj, form, change)

    @admin.display(description="Location", ordering="string_unit__location")
    def location(self, obj: Translation) -> str:
        return obj.string_unit.location

    @admin.display(description="Message ID", ordering="string_unit__message_id")
    def message_id(self, obj: Translation) -> str:
        return obj.string_unit.message_id

    @admin.display(description="Source")
    def short_source(self, obj: Translation) -> str:
        return _truncate(obj.string_unit.source_text)

    @admin.display(boolean=True, description="Has draft")
    def has_machine_draft(self, obj: Translation) -> bool:
        return bool((obj.machine_draft or "").strip())

    @admin.display(boolean=True, description="QA")
    def has_qa_warnings(self, obj: Translation) -> bool:
        return bool(obj.qa_flags)

    @admin.display(description="Warnings")
    def qa_warnings(self, obj: Translation) -> str:
        if not obj.qa_flags:
            return ""

        try:
            return json.dumps(obj.qa_flags, indent=2, ensure_ascii=False, sort_keys=True)
        except TypeError:
            # Fallback for any unexpected non-JSON-serializable objects.
            return str(obj.qa_flags)

    @admin.display(description="Location")
    def display_location(self, obj: Translation) -> str:
        return obj.string_unit.location

    @admin.display(description="Message ID")
    def display_message_id(self, obj: Translation) -> str:
        return obj.string_unit.message_id

    @admin.display(description="Source (English)")
    def display_source_text(self, obj: Translation) -> str:
        return obj.string_unit.source_text

    @admin.display(description="Source hash")
    def display_source_hash(self, obj: Translation) -> str:
        return obj.string_unit.source_hash
