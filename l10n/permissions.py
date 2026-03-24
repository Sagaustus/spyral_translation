"""Shared permission helpers for the l10n app.

Used by both views.py and admin.py to avoid duplicating role-checking logic.
"""

from __future__ import annotations

from .models import LocaleAssignment, TranslatorApplication


def is_superadmin(user) -> bool:
    if not user.is_authenticated:
        return False
    return getattr(user, "is_superuser", False) or user.groups.filter(name="L10N_SUPERADMIN").exists()


def is_approved_reviewer(user) -> bool:
    if not user.is_authenticated:
        return False
    if is_superadmin(user):
        return True
    try:
        app = user.translator_application
    except TranslatorApplication.DoesNotExist:
        return False
    if app.status != TranslatorApplication.ApplicationStatus.APPROVED:
        return False
    return user.groups.filter(name="L10N_REVIEWER").exists()


def is_approved_translator(user) -> bool:
    if not user.is_authenticated:
        return False
    if is_superadmin(user):
        return True
    try:
        app = user.translator_application
    except TranslatorApplication.DoesNotExist:
        return False
    if app.status != TranslatorApplication.ApplicationStatus.APPROVED:
        return False
    return user.groups.filter(name="L10N_TRANSLATOR").exists()


def is_approver(user) -> bool:
    if not user.is_authenticated:
        return False
    if is_superadmin(user):
        return True
    return user.groups.filter(name__in=["L10N_APPROVER", "L10N_SUPERADMIN"]).exists()


def is_reviewer(user) -> bool:
    """Check group membership only (no application check). Used by admin."""
    return user.groups.filter(name="L10N_REVIEWER").exists()


def assigned_locale_ids(user) -> list[int]:
    return list(LocaleAssignment.objects.filter(user=user).values_list("locale_id", flat=True))
