from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_IMAGE_FORMATS = {
    ".jpg": ("JPEG", "image/jpeg", "JPEG"),
    ".jpeg": ("JPEG", "image/jpeg", "JPEG"),
    ".png": ("PNG", "image/png", "PNG"),
}


def validate_and_reencode_photo(uploaded_file):
    """Validate an uploaded image and return a re-encoded copy without metadata."""

    extension = Path(uploaded_file.name).suffix.lower()
    expected = ALLOWED_IMAGE_FORMATS.get(extension)
    if expected is None:
        raise ValidationError("Only JPEG and PNG photos are allowed.")

    expected_format, expected_mime, output_format = expected
    if getattr(uploaded_file, "content_type", expected_mime) != expected_mime:
        raise ValidationError("The photo extension and MIME type do not match.")
    if uploaded_file.size > settings.MAX_PHOTO_SIZE:
        raise ValidationError("The photo exceeds the maximum allowed size.")

    try:
        with Image.open(uploaded_file) as image:
            if image.format != expected_format:
                raise ValidationError("The photo file signature does not match its type.")
            width, height = image.size
            if (
                width > settings.MAX_PHOTO_WIDTH
                or height > settings.MAX_PHOTO_HEIGHT
                or width * height > settings.MAX_PHOTO_PIXELS
            ):
                raise ValidationError("The photo dimensions exceed the allowed limit.")
            image.verify()

        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            if output_format == "JPEG":
                image = image.convert("RGB")
            elif image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            output = BytesIO()
            image.save(output, format=output_format, optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("The uploaded file is not a valid image.") from exc

    safe_extension = ".jpg" if output_format == "JPEG" else ".png"
    filename = f"{uuid4().hex}{safe_extension}"
    return ContentFile(output.getvalue(), name=filename)
