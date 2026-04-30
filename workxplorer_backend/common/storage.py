from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage
from storages.backends.s3boto3 import S3Boto3Storage


def _build_s3_storage() -> Storage:
    return S3Boto3Storage(
        access_key=settings.AWS_ACCESS_KEY_ID,
        secret_key=settings.AWS_SECRET_ACCESS_KEY,
        bucket_name=settings.AWS_STORAGE_BUCKET_NAME,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        default_acl=None,
        querystring_auth=False,
        file_overwrite=False,
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
