from django.urls import path

from . import views

app_name = "assignments"

urlpatterns = [
    path("reports/<int:report_id>/assign/", views.assign_report, name="assign_report"),
    path(
        "technician/reports/<int:report_id>/",
        views.technician_report_detail,
        name="technician_report_detail",
    ),
    path(
        "technician/reports/<int:report_id>/start/",
        views.start_work_view,
        name="start_work",
    ),
    path(
        "technician/reports/<int:report_id>/complete/",
        views.complete_work_view,
        name="complete_work",
    ),
    path(
        "technician/reports/<int:report_id>/hold/",
        views.put_on_hold_view,
        name="put_on_hold",
    ),
]
