from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("new/", views.report_create, name="create"),
    path(
        "<int:report_id>/verify/",
        views.verify_report_view,
        name="verify",
    ),
    path(
        "<int:report_id>/reopen/",
        views.reopen_report_view,
        name="reopen",
    ),
    path(
        "<int:report_id>/comments/",
        views.report_comments,
        name="comments",
    ),
    path(
        "<int:report_id>/history/",
        views.report_history,
        name="history",
    ),
    path("<int:report_id>/", views.report_detail, name="detail"),
    path(
        "<int:report_id>/photos/<int:photo_id>/",
        views.photo_download,
        name="photo_download",
    ),
]
