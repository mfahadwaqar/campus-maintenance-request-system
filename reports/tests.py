from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Building, User
from .models import Category, Photo, Report, StatusHistory


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
        self.building = Building.objects.create(name="Test Building", zone="Test Zone")
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
            username="officer", password="test-password", role=User.Role.OFFICER
        )
        self.client.force_login(self.resident)

    def tearDown(self):
        for photo in Photo.objects.all():
            photo.file.delete(save=False)

    def valid_form_data(self):
        return {
            "category": str(self.category.pk),
            "building": str(self.building.pk),
            "room_location": "Room 204",
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
