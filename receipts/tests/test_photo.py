"""Тесты необязательной загрузки фото чека (бонусная функция)."""
from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from receipts.forms import ReceiptForm
from receipts.models import Receipt
from receipts.promo import promo_settings

from .base import BaseTestCase, valid_payload

VALID_SETTINGS = override_settings(
    RECEIPT_PHOTO_MAX_MB=1,
    RECEIPT_PHOTO_ALLOWED_TYPES=("jpg", "jpeg", "png", "webp"),
)


def make_image(name: str = "receipt.png", content_type: str = "image/png", size_kb: int = 20) -> SimpleUploadedFile:
    """Минимальный валидный PNG нужного размера (валидность проверяет Pillow)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 255, 255)).save(buf, format="PNG")
    data = buf.getvalue()
    if size_kb > len(data) / 1024:
        data = data + b"\0" * (size_kb * 1024 - len(data))
    return SimpleUploadedFile(name, data, content_type=content_type)


@VALID_SETTINGS
class ReceiptPhotoTests(BaseTestCase):
    def setUp(self):
        self.payload = valid_payload(n=40)

    def form(self, payload, photo=None):
        return ReceiptForm(payload, {"photo": photo} if photo else None, user=self.user)

    def test_photo_is_optional(self):
        form = self.form(self.payload)
        self.assertTrue(form.is_valid(), form.errors)
        receipt = form.save()
        self.assertFalse(receipt.photo)

    def test_valid_photo_is_saved(self):
        form = self.form(self.payload, make_image())
        self.assertTrue(form.is_valid(), form.errors)
        receipt = form.save()
        self.assertTrue(receipt.photo)
        self.assertTrue(receipt.photo.name.startswith("receipts/"))

    def test_photo_too_large_rejected(self):
        oversized = make_image(size_kb=promo_settings().photo_max_bytes // 1024 + 512)
        form = self.form(self.payload, oversized)
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)
        self.assertIn("слишком большой", str(form.errors["photo"]))

    def test_disallowed_content_type_rejected(self):
        payload = self.payload
        blob = SimpleUploadedFile("receipt.txt", b"just a text file", content_type="text/plain")
        form = self.form(payload, blob)
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    def test_photo_survives_receipt_save(self):
        form = self.form(self.payload, make_image("check.jpg", "image/jpeg"))
        self.assertTrue(form.is_valid(), form.errors)
        receipt = form.save()
        receipt.refresh_from_db()
        self.assertTrue(receipt.photo.name.endswith((".jpg", ".jpeg")))