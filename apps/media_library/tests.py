import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import MAX_UPLOAD_SIZE, PrivateDocumentForm
from .models import PrivateDocument


class PrivateDocumentTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(
            "docs", "docs@example.test", "A-very-long-password-123", email_verified=True
        )
        self.other = users.objects.create_user(
            "otherdocs", "otherdocs@example.test", "A-very-long-password-123", email_verified=True
        )

    def test_upload_uses_safe_generated_name_and_enforces_ownership(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.client.force_login(self.owner)
            upload = SimpleUploadedFile(
                "../report.pdf", b"%PDF-1.7\nvalid", content_type="application/pdf"
            )
            response = self.client.post(
                reverse("media_library:upload"),
                {
                    "entity_type": "set",
                    "entity_id": "1",
                    "document_type": "invoice",
                    "title": "Report",
                    "file": upload,
                },
            )
            self.assertRedirects(response, reverse("media_library:list"))
            document = PrivateDocument.objects.get()
            self.assertNotIn("report.pdf", document.file.name)
            self.client.force_login(self.other)
            self.assertEqual(
                self.client.get(reverse("media_library:download", args=[document.pk])).status_code,
                404,
            )

    def test_executable_upload_is_rejected(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile("payload.exe", b"MZ", content_type="application/octet-stream")
        response = self.client.post(
            reverse("media_library:upload"),
            {
                "entity_type": "set",
                "entity_id": "1",
                "document_type": "other",
                "title": "Bad",
                "file": upload,
            },
        )
        self.assertContains(response, "nicht erlaubt")
        self.assertFalse(PrivateDocument.objects.exists())

    def test_adversarial_text_upload_matrix_is_rejected_without_write(self):
        self.client.force_login(self.owner)
        cases = [
            SimpleUploadedFile("empty.txt", b"", content_type="text/plain"),
            SimpleUploadedFile("binary.txt", b"hello\x00world", content_type="text/plain"),
            SimpleUploadedFile("wrong.pdf", b"%PDF-1.7", content_type="text/plain"),
            SimpleUploadedFile("broken.json", b"{broken", content_type="application/json"),
            SimpleUploadedFile("invalid.txt", b"\xff\xfe", content_type="text/plain"),
        ]
        for upload in cases:
            response = self.client.post(reverse("media_library:upload"), {
                "entity_type": "set", "entity_id": "1", "document_type": "other",
                "title": "Bad", "file": upload,
            })
            self.assertLess(response.status_code, 500)
        self.assertFalse(PrivateDocument.objects.exists())

    def test_every_supported_upload_type_and_adversarial_class(self):
        valid = {
            "d.pdf": (b"%PDF-1.7\nbody", "application/pdf"),
            "d.png": (b"\x89PNG\r\n\x1a\nbody", "image/png"),
            "d.jpg": (b"\xff\xd8\xffbody", "image/jpeg"),
            "d.jpeg": (b"\xff\xd8\xffbody", "image/jpeg"),
            "d.csv": (b"Name,Qty\nBrick,1\n", "text/csv"),
            "d.json": (b'{"name":"Brick"}', "application/json"),
            "ü.txt": ("gültig".encode(), "text/plain"),
        }
        base = {
            "entity_type": "set", "entity_id": "1", "document_type": "other",
            "title": "Document",
        }
        for name, (payload, mime) in valid.items():
            form = PrivateDocumentForm(
                data=base,
                files={"file": SimpleUploadedFile(name, payload, content_type=mime)},
            )
            self.assertTrue(form.is_valid(), (name, form.errors))
        invalid = [
            SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf"),
            SimpleUploadedFile("huge.txt", b"x" * (MAX_UPLOAD_SIZE + 1), content_type="text/plain"),
            SimpleUploadedFile("wrong.png", b"not-png", content_type="image/png"),
            SimpleUploadedFile("wrong.txt", b"text", content_type="application/pdf"),
            SimpleUploadedFile("binary.json", b"{\x00}", content_type="application/json"),
            SimpleUploadedFile("encoding.txt", b"\xff", content_type="text/plain"),
            SimpleUploadedFile("payload.txt", b"MZ executable", content_type="text/plain"),
            SimpleUploadedFile("script.txt", b"#!/bin/sh\nexit", content_type="text/plain"),
        ]
        for upload in invalid:
            form = PrivateDocumentForm(data=base, files={"file": upload})
            self.assertFalse(form.is_valid(), upload.name)

    def test_other_user_cannot_list_download_or_delete_private_document(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            document = PrivateDocument(
                owner=self.owner, entity_type="set", entity_id="1", title="Secret-owner-only-title",
                original_name="private.txt", mime_type="text/plain", size=6,
            )
            document.file.save("private.txt", SimpleUploadedFile("private.txt", b"secret"), save=True)
            self.client.force_login(self.other)
            self.assertNotContains(self.client.get(reverse("media_library:list")), "Secret-owner-only-title")
            self.assertEqual(self.client.get(reverse("media_library:download", args=[document.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse("media_library:delete", args=[document.pk])).status_code, 404)
            document.refresh_from_db()
            self.assertIsNone(document.deleted_at)
