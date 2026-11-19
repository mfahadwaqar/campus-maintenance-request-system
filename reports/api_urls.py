from django.urls import path

from . import api

app_name = "api"

urlpatterns = [
    path("reports/", api.ReportListCreateAPIView.as_view(), name="report-list"),
    path(
        "officer/reports/",
        api.OfficerReportCreateAPIView.as_view(),
        name="officer-report-create",
    ),
    path("reports/<int:report_id>/", api.ReportDetailAPIView.as_view(), name="report-detail"),
    path(
        "reports/<int:report_id>/status/",
        api.ReportStatusAPIView.as_view(),
        name="report-status",
    ),
    path(
        "reports/<int:report_id>/assign/",
        api.ReportAssignmentAPIView.as_view(),
        name="report-assign",
    ),
    path(
        "reports/<int:report_id>/verify/",
        api.ReportVerificationAPIView.as_view(),
        name="report-verify",
    ),
    path(
        "reports/<int:report_id>/reopen/",
        api.ReportReopenAPIView.as_view(),
        name="report-reopen",
    ),
    path(
        "reports/<int:report_id>/comments/",
        api.ReportCommentsAPIView.as_view(),
        name="report-comments",
    ),
    path(
        "reports/<int:report_id>/history/",
        api.ReportHistoryAPIView.as_view(),
        name="report-history",
    ),
    path(
        "reports/<int:report_id>/photos/<int:photo_id>/",
        api.ReportPhotoAPIView.as_view(),
        name="report-photo",
    ),
    path("notifications/", api.NotificationListAPIView.as_view(), name="notification-list"),
    path("buildings/", api.BuildingListAPIView.as_view(), name="building-list"),
    path(
        "room-locations/",
        api.RoomLocationListAPIView.as_view(),
        name="room-location-list",
    ),
    path("categories/", api.CategoryListAPIView.as_view(), name="category-list"),
    path("units/", api.UnitListAPIView.as_view(), name="unit-list"),
    path("units/results/", api.UnitResultsAPIView.as_view(), name="unit-results"),
]
