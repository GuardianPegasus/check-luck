"""Тесты лимита чеков на пользователя (MAX_RECEIPTS_PER_USER)."""
from __future__ import annotations

from django.test import override_settings

from receipts.forms import ReceiptForm
from receipts.models import Receipt

from .base import BaseTestCase, make_receipt, valid_payload

LIMITED = override_settings(MAX_RECEIPTS_PER_USER=2)


@LIMITED
class ReceiptQuotaTests(BaseTestCase):
    def form(self, payload):
        return ReceiptForm(payload, user=self.user)

    def test_quota_allows_up_to_limit(self):
        make_receipt(self.user, n=50)
        form = self.form(valid_payload(n=51))
        self.assertTrue(form.is_valid(), form.errors)

    def test_quota_blocks_when_limit_reached(self):
        make_receipt(self.user, n=52)
        make_receipt(self.user, n=53)
        form = self.form(valid_payload(n=54))
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        self.assertIn("Лимит", " ".join(form.errors["__all__"]))

    def test_quota_is_per_user(self):
        make_receipt(self.user, n=55)
        make_receipt(self.user, n=56)
        # другой пользователь лимитом не исчерпан
        form = ReceiptForm(valid_payload(n=57), user=self.other)
        self.assertTrue(form.is_valid(), form.errors)

    def test_resubmission_does_not_trip_quota(self):
        """Повторная отправка отклонённого чека не должна считаться новым чеком."""
        rejected = make_receipt(self.user, n=58, status=Receipt.Status.REJECTED)
        make_receipt(self.user, n=59, status=Receipt.Status.APPROVED)
        rejected.reject("Магазин не участвует")

        form = self.form(valid_payload(n=58))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Receipt.objects.filter(user=self.user).count(), 2)