from django.core.files.uploadedfile import SimpleUploadedFile

from api.chat.serializers import MessageCreateSerializer


def test_message_create_serializer_allows_supported_attachment_extensions():
    allowed_filenames = [
        "image.png",
        "image.jpg",
        "image.jpeg",
        "image.webp",
        "video.mp4",
        "video.mov",
        "video.webm",
        "document.pdf",
        "document.doc",
        "document.docx",
        "notes.txt",
    ]

    for filename in allowed_filenames:
        serializer = MessageCreateSerializer(
            data={
                "text": "",
                "file": SimpleUploadedFile(filename, b"content"),
            }
        )

        assert serializer.is_valid(), serializer.errors


def test_message_create_serializer_rejects_unsupported_attachment_extension():
    serializer = MessageCreateSerializer(
        data={
            "text": "",
            "file": SimpleUploadedFile("archive.zip", b"content"),
        }
    )

    assert not serializer.is_valid()
    assert "file" in serializer.errors
