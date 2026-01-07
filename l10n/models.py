import hashlib
import unicodedata

from django.conf import settings
from django.db import models


def compute_source_hash(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Locale(models.Model):
    code = models.SlugField(max_length=32, unique=True)
    bcp47 = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    script = models.CharField(max_length=16, blank=True, null=True)
    is_rtl = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    legacy_column = models.CharField(max_length=64, blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class StringUnit(models.Model):
    location = models.CharField(max_length=255)
    message_id = models.CharField(max_length=255)
    source_text = models.TextField(blank=True)
    source_updated_on = models.CharField(max_length=64, blank=True)
    source_hash = models.CharField(max_length=64, editable=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "message_id"],
                name="uniq_location_message_id",
            ),
        ]

    def save(self, *args, **kwargs):
        new_hash = compute_source_hash(self.source_text)
        old_hash = None
        if self.pk:
            old_hash = (
                StringUnit.objects.filter(pk=self.pk).values_list("source_hash", flat=True).first()
            )
        self.source_hash = new_hash
        super().save(*args, **kwargs)

        if old_hash and old_hash != new_hash:
            Translation.objects.filter(
                string_unit=self,
                approved_text__isnull=False,
            ).exclude(
                approved_text=""
            ).update(status=Translation.TranslationStatus.STALE)

    def __str__(self) -> str:
        return f"{self.location} :: {self.message_id}"


class Translation(models.Model):
    class TranslationStatus(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        STALE = "STALE", "Stale"
        IN_REVIEW = "IN_REVIEW", "In review"
        MACHINE_DRAFT = "MACHINE_DRAFT", "Machine draft"
        REJECTED = "REJECTED", "Rejected"
        FLAGGED = "FLAGGED", "Flagged"

    class TranslationProvenance(models.TextChoices):
        IMPORTED = "IMPORTED", "Imported"
        HUMAN = "HUMAN", "Human"
        LLM = "LLM", "LLM"
        MT = "MT", "MT"

    string_unit = models.ForeignKey(StringUnit, on_delete=models.CASCADE)
    locale = models.ForeignKey(Locale, on_delete=models.CASCADE)

    approved_text = models.TextField(blank=True, null=True)
    reviewer_text = models.TextField(blank=True, null=True)
    machine_draft = models.TextField(blank=True, null=True)

    qa_flags = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=32,
        choices=TranslationStatus.choices,
        default=TranslationStatus.IN_REVIEW,
    )
    provenance = models.CharField(
        max_length=16,
        choices=TranslationProvenance.choices,
        default=TranslationProvenance.HUMAN,
    )
    source_hash_at_last_update = models.CharField(max_length=64, blank=True)

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["string_unit", "locale"],
                name="uniq_string_unit_locale",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.locale.code} :: {self.string_unit.location} :: {self.string_unit.message_id}"

    def refresh_qa_flags(self, candidate_text: str) -> None:
        from .services.qa import compute_qa_flags

        source = ""
        if self.string_unit_id:
            source = self.string_unit.source_text or ""

        flags = compute_qa_flags(source=source, target=candidate_text or "")

        # Only warn about empty translations when a user tries to approve.
        if self.status != Translation.TranslationStatus.APPROVED:
            flags = [flag for flag in flags if flag.get("code") != "empty_translation"]

        self.qa_flags = flags

    def save(self, *args, **kwargs):
        approved = (self.approved_text or "").strip()
        reviewer = (self.reviewer_text or "").strip()
        machine = (self.machine_draft or "").strip()

        if approved:
            candidate = approved
        elif reviewer:
            candidate = reviewer
        elif machine:
            candidate = machine
        else:
            candidate = ""

        self.refresh_qa_flags(candidate)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = list(set(update_fields) | {"qa_flags"})

        return super().save(*args, **kwargs)


class LocaleAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="l10n_locale_assignments",
    )
    locale = models.ForeignKey(
        Locale,
        on_delete=models.CASCADE,
        related_name="reviewer_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "locale"],
                name="uniq_locale_assignment_user_locale",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.locale.code}"
