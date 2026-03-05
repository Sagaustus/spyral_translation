from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    # Public
    path("", views.home, name="l10n_home"),
    path("about/", views.about, name="l10n_about"),
    path("workflow/", views.workflow, name="l10n_workflow"),
    path("progress/", views.progress, name="l10n_progress"),
    path("team/", views.team, name="l10n_team"),
    path("call-for-translators/", views.call_translators, name="l10n_call_translators"),
    # Auth
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="l10n/auth_login.html"),
        name="l10n_login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="l10n_logout"),
    # Translator workflow
    path("apply/", views.apply, name="l10n_apply"),
    path("application/", views.application_status, name="l10n_application"),
    path("review/", views.review_queue, name="l10n_review"),
    path("review/<int:translation_id>/", views.review_detail, name="l10n_review_detail"),
    path("translate/", views.translator_queue, name="l10n_translate"),
    path("translate/<int:translation_id>/", views.translator_detail, name="l10n_translate_detail"),
    path("approve/", views.approver_queue, name="l10n_approve"),
    path("approve/<int:translation_id>/", views.approver_detail, name="l10n_approve_detail"),
    # Staff
    path("dashboard/", views.dashboard, name="l10n_dashboard"),
    path("ai/", views.ai_progress_dashboard, name="l10n_ai_dashboard"),
    path("import/", views.import_voyant_csv, name="l10n_import_voyant_csv"),
    path("export/yo/", views.export_yo_csv, name="l10n_export_yo_csv"),
    path("export/<str:locale_code>/", views.export_locale_csv, name="l10n_export_locale_csv"),
    path("pipeline/", views.trigger_pipeline, name="l10n_trigger_pipeline"),
]
