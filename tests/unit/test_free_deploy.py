"""Tests for the free-hosting changes: photos kept in the database, DATABASE_URL, presentation accounts.

Render's free plan has no persistent disk, so uploaded photos must live in PostgreSQL. These tests show
that the database storage behaves like the file storage the rest of the code already uses.
"""

from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.urls import reverse

from accounts.models import User
from campus_maintainance_request_system.dburl import database_settings
from reports.models import Photo
from reports.storage import DatabasePhotoStorage, build_private_photo_storage
from tests.conftest import jpeg_upload

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- database photo storage

def test_a_saved_photo_can_be_read_back_unchanged():
    storage = DatabasePhotoStorage()
    name = storage.save("reports/abc.jpg", ContentFile(b"\xff\xd8photo-bytes"))

    with storage.open(name) as stored:
        assert stored.read() == b"\xff\xd8photo-bytes"
    assert name == "reports/abc.jpg"
    assert storage.exists(name)
    assert storage.size(name) == len(b"\xff\xd8photo-bytes")


def test_saving_the_same_name_twice_never_overwrites_the_first_photo():
    storage = DatabasePhotoStorage()
    first = storage.save("reports/same.jpg", ContentFile(b"first"))
    second = storage.save("reports/same.jpg", ContentFile(b"second"))

    assert first != second
    assert storage.open(first).read() == b"first"
    assert storage.open(second).read() == b"second"


def test_a_deleted_photo_is_gone_and_deleting_twice_is_harmless():
    storage = DatabasePhotoStorage()
    name = storage.save("reports/gone.jpg", ContentFile(b"x"))

    storage.delete(name)
    storage.delete(name)

    assert not storage.exists(name)
    with pytest.raises(FileNotFoundError):
        storage.open(name)


def test_the_database_storage_never_hands_out_a_public_url():
    with pytest.raises(ValueError):
        DatabasePhotoStorage().url("reports/abc.jpg")


def test_the_setting_chooses_the_storage_backend():
    assert isinstance(build_private_photo_storage("database"), DatabasePhotoStorage)
    assert not isinstance(build_private_photo_storage("filesystem"), DatabasePhotoStorage)
    with pytest.raises(ValueError):
        build_private_photo_storage("somewhere-else")


def test_a_resident_photo_survives_without_any_file_on_disk_and_stays_private(
    client, resident, other_resident, new_report, flow, technician
):
    """The whole path: submit with a photo, assign, then the technician and the owner see it; a stranger does not."""
    storage = DatabasePhotoStorage()
    with mock.patch("reports.storage.private_photo_storage", storage), mock.patch(
        "reports.services.private_photo_storage", storage
    ):
        report = new_report(photo=jpeg_upload())
        flow.assign(report)
        photo = Photo.objects.get(report=report)
        url = reverse("reports:photo_download", args=[report.pk, photo.pk])

        seen = {}
        for name, user in (("owner", resident), ("technician", technician), ("stranger", other_resident)):
            client.force_login(user)
            response = client.get(url)
            seen[name] = response.status_code
            if response.status_code == 200:
                body = b"".join(response.streaming_content)
                assert body[:2] == b"\xff\xd8"  # a JPEG, read from the database

    assert seen == {"owner": 200, "technician": 200, "stranger": 404}
    assert storage.exists(photo.file_path)


# ---------------------------------------------------------------- DATABASE_URL

def test_database_url_is_split_into_django_settings():
    cfg = database_settings(
        {"DATABASE_URL": "postgresql://neon_user:p%40ss@ep-cool-123.aws.neon.tech/neondb?sslmode=require"}
    )

    assert cfg["NAME"] == "neondb"
    assert cfg["USER"] == "neon_user"
    assert cfg["PASSWORD"] == "p@ss"
    assert cfg["HOST"] == "ep-cool-123.aws.neon.tech"
    assert cfg["PORT"] == "5432"
    assert cfg["OPTIONS"] == {"sslmode": "require"}


def test_separate_postgres_variables_still_work_without_a_url():
    cfg = database_settings(
        {"POSTGRES_DB": "d", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_HOST": "h", "POSTGRES_PORT": "1"}
    )

    assert (cfg["NAME"], cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"]) == ("d", "u", "p", "h", "1")
    assert "OPTIONS" not in cfg


def test_a_database_url_for_another_database_kind_is_refused():
    with pytest.raises(ValueError):
        database_settings({"DATABASE_URL": "mysql://u:p@h/db"})


# ---------------------------------------------------------------- presentation accounts

def test_presentation_accounts_are_created_with_units_and_can_be_run_twice():
    call_command("seed_reference_data", verbosity=0)
    call_command("seed_campus_reference_data", verbosity=0)
    with mock.patch.dict("os.environ", {"PRESENTATION_USER_PASSWORD": "Present-Test-9x!"}):
        call_command("seed_presentation_accounts", verbosity=0)
        call_command("seed_presentation_accounts", verbosity=0)

    staff = User.objects.get(username="staff.sarah")
    assert staff.role == "CALL_CENTER_STAFF"
    assert User.objects.filter(role="RESIDENT", username__startswith="resident.").count() == 2
    technicians = User.objects.filter(role="TECHNICIAN_CONTRACTOR", username__startswith="tech.")
    assert technicians.count() == 9
    assert all(t.unit_id for t in technicians)
    assert User.objects.get(username="tech.electrical").unit.name == "Electrical Services"
    assert staff.check_password("Present-Test-9x!")


def test_presentation_accounts_need_a_password_from_the_environment():
    from django.core.management.base import CommandError

    with mock.patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("PRESENTATION_USER_PASSWORD", None)
        with pytest.raises(CommandError):
            call_command("seed_presentation_accounts", verbosity=0)
