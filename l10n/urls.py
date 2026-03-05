from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="l10n_home"),
    path("about/", views.about, name="l10n_about"),
    path("team/", views.team, name="l10n_team"),
    path("call-for-translators/", views.call_translators, name="l10n_call_translators"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="l10n/auth_login.html"),
        name="l10n_login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="l10n_logout"),
    path("apply/", views.apply, name="l10n_apply"),
    path("application/", views.application_status, name="l10n_application"),
    path("review/", views.review_queue, name="l10n_review"),
    path("review/<int:translation_id>/", views.review_detail, name="l10n_review_detail"),
    path("dashboard/", views.dashboard, name="l10n_dashboard"),
    path("import/", views.import_voyant_csv, name="l10n_import_voyant_csv"),
    path("export/yo/", views.export_yo_csv, name="l10n_export_yo_csv"),
]
