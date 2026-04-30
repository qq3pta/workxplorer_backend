from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage


def _build_s3_storage() -> Storage:
    from storages.backends.s3 import S3Storage

    return S3Storage(
        bucket_name=settings.AWS_STORAGE_BUCKET_NAME,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        access_key=settings.AWS_S3_ACCESS_KEY_ID,
        secret_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        default_acl="public-read",
        querystring_auth=False,
        file_overwrite=False,
        addressing_style="virtual",
    )


def avatar_storage() -> Storage:
    """
    Storage callable для `User.photo`. Используется как `storage=avatar_storage`,
    чтобы Django мог сериализовать его в миграциях и подменить FS-бэкенд,
    когда S3 не сконфигурирован.
    """
    if getattr(settings, "USE_S3_AVATAR_STORAGE", False):
        return _build_s3_storage()
    return FileSystemStorage()
