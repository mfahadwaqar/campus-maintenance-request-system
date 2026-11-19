"""Unit tests for photo validation (equivalence classes and boundary values).

Rule under test (reports/photo_pipeline.py): only real JPEG or PNG images within the
size and dimension limits are accepted, and the stored copy has its metadata removed.
"""

from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from reports.photo_pipeline import validate_and_reencode_photo

pytestmark = [pytest.mark.unit, pytest.mark.blackbox]


def image_bytes(fmt="JPEG", size=(8, 8), exif=False):
    output = BytesIO()
    image = Image.new("RGB", size, color="green")
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCameraMaker"  # the Make tag
        image.save(output, format=fmt, exif=data)
    else:
        image.save(output, format=fmt)
    return output.getvalue()


def upload(name, data, content_type):
    return SimpleUploadedFile(name, data, content_type=content_type)


def test_a_valid_jpeg_is_accepted_and_given_a_random_name():
    result = validate_and_reencode_photo(upload("my holiday.jpg", image_bytes(), "image/jpeg"))

    assert result.name.endswith(".jpg")
    assert "holiday" not in result.name
    assert Image.open(BytesIO(result.read())).format == "JPEG"


def test_a_valid_png_is_accepted():
    result = validate_and_reencode_photo(upload("a.png", image_bytes("PNG"), "image/png"))

    assert result.name.endswith(".png")


def test_metadata_is_removed_from_the_stored_copy():
    original = image_bytes(exif=True)
    assert len(Image.open(BytesIO(original)).getexif()) > 0  # arrange: the input really has EXIF

    result = validate_and_reencode_photo(upload("p.jpg", original, "image/jpeg"))

    assert len(Image.open(BytesIO(result.read())).getexif()) == 0


@pytest.mark.parametrize(
    "name,fmt,content_type",
    [
        ("a.gif", "GIF", "image/gif"),       # a real image in a format we do not accept
        ("a.bmp", "BMP", "image/bmp"),
        ("a.webp", "WEBP", "image/webp"),
    ],
)
def test_other_image_formats_are_refused(name, fmt, content_type):
    with pytest.raises(ValidationError, match="Only JPEG and PNG"):
        validate_and_reencode_photo(upload(name, image_bytes(fmt), content_type))


def test_a_text_file_renamed_to_jpg_is_refused():
    with pytest.raises(ValidationError, match="not a valid image"):
        validate_and_reencode_photo(upload("evil.jpg", b"this is not an image", "image/jpeg"))


def test_a_png_renamed_to_jpg_is_refused_because_the_signature_differs():
    with pytest.raises(ValidationError, match="signature"):
        validate_and_reencode_photo(upload("a.jpg", image_bytes("PNG"), "image/jpeg"))


def test_extension_and_mime_type_must_agree():
    with pytest.raises(ValidationError, match="MIME"):
        validate_and_reencode_photo(upload("a.jpg", image_bytes(), "image/png"))


def test_size_boundary_exactly_at_the_limit_is_accepted(settings):
    data = image_bytes()
    settings.MAX_PHOTO_SIZE = len(data)

    assert validate_and_reencode_photo(upload("a.jpg", data, "image/jpeg"))


def test_size_boundary_one_byte_over_the_limit_is_refused(settings):
    data = image_bytes()
    settings.MAX_PHOTO_SIZE = len(data) - 1

    with pytest.raises(ValidationError, match="maximum allowed size"):
        validate_and_reencode_photo(upload("a.jpg", data, "image/jpeg"))


def test_width_boundary(settings):
    settings.MAX_PHOTO_WIDTH = 8
    settings.MAX_PHOTO_PIXELS = 10_000

    assert validate_and_reencode_photo(upload("a.jpg", image_bytes(size=(8, 8)), "image/jpeg"))
    with pytest.raises(ValidationError, match="dimensions"):
        validate_and_reencode_photo(upload("a.jpg", image_bytes(size=(9, 8)), "image/jpeg"))


def test_total_pixel_boundary(settings):
    settings.MAX_PHOTO_PIXELS = 64  # 8 x 8

    assert validate_and_reencode_photo(upload("a.jpg", image_bytes(size=(8, 8)), "image/jpeg"))
    with pytest.raises(ValidationError, match="dimensions"):
        validate_and_reencode_photo(upload("a.jpg", image_bytes(size=(9, 8)), "image/jpeg"))
