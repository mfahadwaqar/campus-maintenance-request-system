from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.dashboard_redirect, name="home"),
    path("login/", views.RoleLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path(
        "officer/reports/<int:report_id>/review/",
        views.begin_report_review,
        name="begin_report_review",
    ),
    path(
        "officer/reports/<int:report_id>/",
        views.officer_report_detail,
        name="officer_report_detail",
    ),
    path(
        "officer/reports/<int:report_id>/priority/",
        views.update_report_priority,
        name="update_report_priority",
    ),
    path(
        "officer/reports/<int:report_id>/reject/",
        views.reject_report_view,
        name="reject_report",
    ),
    path(
        "officer/reports/<int:report_id>/reopen/",
        views.officer_reopen_report,
        name="officer_reopen_report",
    ),
    path("dashboard/", views.dashboard_redirect, name="dashboard"),
    path(
        "resident/dashboard/",
        views.resident_dashboard,
        name="resident_dashboard",
    ),
    path("officer/dashboard/", views.officer_dashboard, name="officer_dashboard"),
    path(
        "technician/dashboard/",
        views.technician_dashboard,
        name="technician_dashboard",
    ),
    path("unit-results/", views.unit_results, name="unit_results"),
]
