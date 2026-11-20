from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage


class PrivatePhotoStorage(FileSystemStorage):
    """Photos as files in a folder outside the project (the default; needs a disk that survives restarts)."""

    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


class DatabasePhotoStorage(Storage):
    """Photos as rows in PostgreSQL, for hosts without a persistent disk (for example Render's free plan).

    Photos are already re-encoded and size-limited before they get here, so they are small. They stay
    private because they are only ever served through the permission-checked download view.
    """

    @staticmethod
    def _rows():
        return apps.get_model("reports", "StoredPhotoFile").objects

    def _open(self, name, mode="rb"):
        row = self._rows().filter(name=name).values_list("content", flat=True).first()
        if row is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(row), name=name)

    def _save(self, name, content):
        data = b"".join(content.chunks())
        self._rows().create(name=name, content=data, size_bytes=len(data))
        return name

    def delete(self, name):
        self._rows().filter(name=name).delete()

    def exists(self, name):
        return self._rows().filter(name=name).exists()

    def size(self, name):
        size = self._rows().filter(name=name).values_list("size_bytes", flat=True).first()
        if size is None:
            raise FileNotFoundError(name)
        return size

    def url(self, name):
        raise ValueError("Photos have no public address; they are served by the permission-checked view.")


def build_private_photo_storage(backend):
    if backend == "database":
        return DatabasePhotoStorage()
    if backend == "filesystem":
        return PrivatePhotoStorage()
    raise ValueError(f"PHOTO_STORAGE must be 'filesystem' or 'database', not {backend!r}.")


private_photo_storage = build_private_photo_storage(getattr(settings, "PHOTO_STORAGE", "filesystem"))
