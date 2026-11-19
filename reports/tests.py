from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Building, RoomLocation, Unit, UnitKind, User
from .models import Category, Comment, Photo, Report, StatusHistory
from .services import add_comment, apply_transition


def image_upload(
    *, name="fixture.jpg", image_format="JPEG", content_type=None, exif=False
):
    image = Image.new("RGB", (24, 16), color=(35, 90, 130))
    options = {}
    if exif:
        metadata = Image.Exif()
        metadata[0x010E] = "synthetic metadata"
        metadata[0x0112] = 1
        options["exif"] = metadata
    output = BytesIO()
    image.save(output, format=image_format, **options)
    mime_type = content_type or (
        "image/jpeg" if image_format == "JPEG" else "image/png"
    )
    return SimpleUploadedFile(name, output.getvalue(), content_type=mime_type)


class ReportSubmissionTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Dormitory A", zone="Zone 1")
        RoomLocation.objects.get_or_create(
            code="A204",
            defaults={
                "name": "Dormitory A",
                "location_type": RoomLocation.LocationType.DORMITORY,
            },
        )
        self.category = Category.objects.create(name="Test Plumbing")
        self.resident = User.objects.create_user(
            username="resident", password="test-password", role=User.Role.RESIDENT
        )
        self.other_resident = User.objects.create_user(
            username="other_resident",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.officer = User.objects.create_user(
            username="officer", password="test-password", role=User.Role.CALL_CENTER_STAFF
        )
        self.client.force_login(self.resident)

    def tearDown(self):
        for photo in Photo.objects.all():
            photo.file.delete(save=False)

    def valid_form_data(self):
        return {
            "category": str(self.category.pk),
            "building": str(self.building.pk),
            "room_location": "A204",
            "room_verified": "on",
            "title": "Leaking sink",
            "description": "Water is dripping under the sink.",
            "requested_urgency": "MEDIUM",
        }

    def submit_report(self, **overrides):
        data = self.valid_form_data()
        data.update(overrides)
        return self.client.post(reverse("reports:create"), data)

    def test_valid_submission_creates_report_and_initial_status_history(self):
        response = self.submit_report()

        report = Report.objects.get()
        self.assertRedirects(response, reverse("reports:detail", args=(report.pk,)))
        self.assertEqual(report.resident, self.resident)
        self.assertEqual(report.status, Report.Status.SUBMITTED)
        self.assertEqual(report.version, 1)
        history = StatusHistory.objects.get(report=report)
        self.assertEqual(history.old_status, "")
        self.assertEqual(history.new_status, Report.Status.SUBMITTED)
        self.assertEqual(history.changed_by, self.resident)

    def test_invalid_submission_is_rejected_without_creating_records(self):
        response = self.submit_report(title="", requested_urgency="URGENT")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertEqual(Report.objects.count(), 0)
        self.assertEqual(StatusHistory.objects.count(), 0)

    def test_nonresident_cannot_open_submission_form(self):
        self.client.force_login(self.officer)

        response = self.client.get(reverse("reports:create"))

        self.assertEqual(response.status_code, 404)

    def test_report_and_photo_are_hidden_from_other_resident(self):
        response = self.submit_report(photo=image_upload())
        report = Report.objects.get()
        photo = Photo.objects.get(report=report)
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.other_resident)
        detail_response = self.client.get(
            reverse("reports:detail", args=(report.pk,))
        )
        photo_response = self.client.get(
            reverse(
                "reports:photo_download",
                args=(report.pk, photo.pk),
            )
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(photo_response.status_code, 404)

    def test_resident_report_list_contains_only_their_own_reports(self):
        self.submit_report()
        own_report = Report.objects.get()
        self.client.force_login(self.other_resident)
        self.submit_report(title="Another resident's request")
        other_report = Report.objects.exclude(pk=own_report.pk).get()

        self.client.force_login(self.resident)
        response = self.client.get(reverse("reports:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_report.title)
        self.assertNotContains(response, other_report.title)

    def test_officer_dashboard_shows_resident_submitted_report(self):
        self.submit_report(title="Leaking sink for officer")
        self.client.force_login(self.officer)

        response = self.client.get(reverse("accounts:officer_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leaking sink for officer")
        self.assertContains(
            response,
            reverse("reports:detail", args=(Report.objects.get().pk,)),
        )

    def test_disguised_photo_is_rejected(self):
        disguised = image_upload(
            name="not-a-jpeg.jpg", image_format="PNG", content_type="image/jpeg"
        )

        response = self.submit_report(photo=disguised)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "signature does not match")
        self.assertEqual(Report.objects.count(), 0)

    @override_settings(MAX_PHOTO_SIZE=100)
    def test_oversized_photo_is_rejected(self):
        image = Image.new("RGB", (100, 100), color=(100, 120, 140))
        output = BytesIO()
        image.save(output, format="JPEG", quality=100)
        uploaded = SimpleUploadedFile(
            "large.jpg", output.getvalue(), content_type="image/jpeg"
        )
        self.assertGreater(uploaded.size, settings.MAX_PHOTO_SIZE)

        response = self.submit_report(photo=uploaded)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exceeds the maximum allowed size")
        self.assertEqual(Report.objects.count(), 0)

    def test_uploaded_photo_is_reencoded_without_exif_and_uses_random_filename(self):
        response = self.submit_report(
            photo=image_upload(name="resident-photo.jpg", exif=True)
        )
        photo = Photo.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("resident-photo", photo.file.name)
        self.assertTrue(photo.file.name.startswith("reports/"))
        self.assertFalse(
            Path(settings.PRIVATE_MEDIA_ROOT)
            .resolve()
            .is_relative_to(Path(settings.BASE_DIR).resolve())
        )

        with photo.file.open("rb") as stored_file:
            with Image.open(stored_file) as stored_image:
                self.assertEqual(dict(stored_image.getexif()), {})

    @override_settings(MAX_PHOTO_WIDTH=12)
    def test_photo_exceeding_dimension_limit_is_rejected(self):
        response = self.submit_report(photo=image_upload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dimensions exceed the allowed limit")
        self.assertEqual(Report.objects.count(), 0)

    def test_status_history_cannot_be_updated_or_deleted(self):
        self.submit_report()
        history = StatusHistory.objects.get()
        history.note = "edited"

        with self.assertRaises(ValidationError):
            history.save()
        with self.assertRaises(ValidationError):
            history.delete()
        with self.assertRaises(ValidationError):
            StatusHistory.objects.filter(pk=history.pk).update(note="edited")
        with self.assertRaises(ValidationError):
            StatusHistory.objects.filter(pk=history.pk).delete()

        history.refresh_from_db()
        self.assertEqual(history.note, "Report submitted")

    def test_private_photo_download_returns_image_only_to_authorized_user(self):
        self.submit_report(photo=image_upload())
        photo = Photo.objects.get()
        response = self.client.get(
            reverse(
                "reports:photo_download",
                args=(photo.report_id, photo.pk),
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))

    def test_description_with_script_markup_renders_as_text(self):
        self.submit_report(description="<script>window.alert(1)</script>")
        report = Report.objects.get()

        response = self.client.get(reverse("reports:detail", args=(report.pk,)))

        self.assertContains(response, "&lt;script&gt;window.alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>window.alert(1)</script>")


class TechnicianReportAccessTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Technician Scope Building")
        self.category = Category.objects.create(name="Technician Scope Category")
        self.assigned_unit = Unit.objects.create(
            name="Assigned Unit", kind=UnitKind.INTERNAL
        )
        self.other_unit = Unit.objects.create(name="Other Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="scope_resident", role=User.Role.RESIDENT
        )
        self.officer = User.objects.create_user(
            username="scope_officer", role=User.Role.CALL_CENTER_STAFF
        )
        self.assigned_technician = User.objects.create_user(
            username="assigned_technician",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.assigned_unit,
        )
        self.unit_colleague = User.objects.create_user(
            username="unit_colleague",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.assigned_unit,
        )
        self.other_technician = User.objects.create_user(
            username="other_technician",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.other_unit,
        )
        self.report = Report.objects.create(
            ticket_no="CMR-2026-821001-000001",
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="SV04-101",
            title="Restricted technician report",
            description="Report body visible only to the assigned unit.",
            channel="WEB",
        )
        apply_transition(
            self.report,
            Report.Status.ASSIGNED,
            self.officer,
            unit=self.assigned_unit,
            technician=self.assigned_technician,
        )
        self.report.refresh_from_db()
        self.comment = Comment.objects.create(
            report=self.report,
            author=self.resident,
            body="Resident comment restricted to the assigned unit.",
        )
        self.photo = Photo.objects.create(
            report=self.report,
            uploaded_by=self.resident,
            stage=Photo.Stage.REPORT,
            file_path="reports/scope-test-photo.jpg",
            content_type="image/jpeg",
            size_bytes=1,
        )

    def test_other_unit_technician_cannot_access_report_or_related_data(self):
        self.client.force_login(self.other_technician)

        list_response = self.client.get(reverse("reports:list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.report.title)

        restricted_urls = (
            reverse("reports:detail", args=(self.report.pk,)),
            reverse("reports:history", args=(self.report.pk,)),
            reverse("reports:comments", args=(self.report.pk,)),
            reverse(
                "reports:photo_download",
                args=(self.report.pk, self.photo.pk),
            ),
        )
        for url in restricted_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        self.assertFalse(
            Comment.objects.for_user(self.other_technician, self.report).exists()
        )

    def test_same_unit_nonassignee_cannot_access_report_or_comments(self):
        self.client.force_login(self.unit_colleague)

        detail_response = self.client.get(
            reverse("reports:detail", args=(self.report.pk,))
        )
        comments_response = self.client.get(
            reverse("reports:comments", args=(self.report.pk,))
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(comments_response.status_code, 404)
        self.assertFalse(Comment.objects.for_user(self.unit_colleague, self.report).exists())

    def test_named_active_assignee_can_access_report_and_comments(self):
        self.client.force_login(self.assigned_technician)

        detail_response = self.client.get(
            reverse("reports:detail", args=(self.report.pk,))
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.report.title)
        self.assertContains(detail_response, self.comment.body)

    def test_ended_assignment_does_not_grant_technician_access(self):
        assignment = self.report.assignments.get(is_active=True)
        assignment.is_active = False
        assignment.ended_at = timezone.now()
        assignment.end_reason = "REASSIGNED"
        assignment.save(update_fields=("is_active", "ended_at", "end_reason"))
        self.client.force_login(self.assigned_technician)

        self.assertEqual(
            self.client.get(
                reverse("reports:detail", args=(self.report.pk,))
            ).status_code,
            404,
        )


class CommentRulesTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Comment Building")
        self.category = Category.objects.create(name="Comment Category")
        self.unit = Unit.objects.create(name="Comment Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="comment_resident", password="test-password-only", role=User.Role.RESIDENT
        )
        self.staff = User.objects.create_user(
            username="comment_staff", password="test-password-only", role=User.Role.CALL_CENTER_STAFF
        )
        self.worker = User.objects.create_user(
            username="comment_worker", password="test-password-only",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )

    def make_report(self, status):
        report = Report.objects.create(
            ticket_no=f"CMR-2026-1-{Report.objects.count() + 1:06d}",
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="A101",
            title="Comment test",
            description="Comment test",
            channel="WEB",
            status=Report.Status.SUBMITTED,
        )
        if status == Report.Status.CLOSED:
            transitions = [
                (Report.Status.UNDER_REVIEW, User.Role.CALL_CENTER_STAFF),
                (Report.Status.ASSIGNED, User.Role.CALL_CENTER_STAFF),
                (Report.Status.IN_PROGRESS, User.Role.TECHNICIAN_CONTRACTOR),
                (Report.Status.COMPLETED, User.Role.TECHNICIAN_CONTRACTOR),
                (Report.Status.CLOSED, "SYSTEM"),
            ]
        elif status == Report.Status.ASSIGNED:
            transitions = [(status, User.Role.CALL_CENTER_STAFF)]
        elif status == Report.Status.REOPENED:
            transitions = [
                (Report.Status.UNDER_REVIEW, User.Role.CALL_CENTER_STAFF),
                (Report.Status.ASSIGNED, User.Role.CALL_CENTER_STAFF),
                (Report.Status.IN_PROGRESS, User.Role.TECHNICIAN_CONTRACTOR),
                (Report.Status.COMPLETED, User.Role.TECHNICIAN_CONTRACTOR),
                (Report.Status.CLOSED, "SYSTEM"),
                (Report.Status.ASSIGNED, User.Role.RESIDENT),
            ]
        else:
            transitions = [(status, User.Role.SYSTEM)]
        with connection.cursor() as cursor:
            current = Report.Status.SUBMITTED
            for new_status, role in transitions:
                cursor.execute(
                    "SELECT set_config('app.current_user_role', %s, true)",
                    [role],
                )
                cursor.execute(
                    "UPDATE reports_report SET status = %s WHERE id = %s",
                    [new_status, report.pk],
                )
                current = new_status
        report.refresh_from_db()
        return report

    def test_item_3_comments_are_allowed_after_reopening_to_assigned(self):
        for status in (Report.Status.ASSIGNED, Report.Status.REOPENED):
            with self.subTest(status=status):
                report = self.make_report(status)
                comment = add_comment(
                    report_id=report.pk, author=self.resident, body="Resident update"
                )
                self.assertEqual(comment.kind, Comment.Kind.COMMENT)
                report.refresh_from_db()
                self.assertTrue(report.awaiting_call_center_response)

    def test_staff_reply_clears_resident_flag(self):
        report = self.make_report(Report.Status.ASSIGNED)
        add_comment(report_id=report.pk, author=self.resident, body="Resident update")
        add_comment(report_id=report.pk, author=self.staff, body="Staff update")
        report.refresh_from_db()
        self.assertFalse(report.awaiting_call_center_response)

    def test_closed_comment_is_refused_for_service_and_post(self):
        report = self.make_report(Report.Status.CLOSED)
        count = Comment.objects.filter(report=report).count()
        with self.assertRaises(ValidationError):
            add_comment(report_id=report.pk, author=self.resident, body="Too late")

        self.client.force_login(self.resident)
        response = self.client.post(
            reverse("reports:comments", args=(report.pk,)),
            {"body": "Direct post"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.filter(report=report).count(), count)

    def test_comment_form_has_no_kind_field(self):
        report = self.make_report(Report.Status.ASSIGNED)
        self.client.force_login(self.resident)
        response = self.client.get(reverse("reports:detail", args=(report.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="kind"')
