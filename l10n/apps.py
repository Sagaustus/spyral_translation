from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _ensure_groups(sender, **_kwargs):
    # Import lazily so app loading/migrations remain safe.
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name="L10N_REVIEWER")
    Group.objects.get_or_create(name="L10N_SUPERADMIN")


class L10NConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "l10n"

    def ready(self):
        post_migrate.connect(_ensure_groups, sender=self)
