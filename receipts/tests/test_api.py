"""Тесты API: /api/receipts/ отдаёт только чеки текущего пользователя."""
from __future__ import annotations

from django.urls import reverse

from receipts.models import Receipt

from .base import BaseTestCase, make_receipt


class ReceiptApiTests(BaseTestCase):
    def setUp(self):
        self.url = reverse("receipts:api_receipts")

    def test_anonymous_gets_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")

    def test_returns_only_own_receipts(self):
        make_receipt(self.user, n=1)
        make_receipt(self.other, n=2, status=Receipt.Status.APPROVED)
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)

    def test_cannot_read_other_users_receipts_via_params(self):
        mine = make_receipt(self.user, n=3)
        theirs = make_receipt(self.other, n=4)
        self.client.force_login(self.user)

        for params in (
            {"user": self.other.pk},
            {"user_id": self.other.pk},
            {"user": self.other.username},
            {"username": self.other.username},
            {"id": theirs.pk},
            {"receipt": theirs.pk},
            {"owner": self.other.pk},
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                ids = {r["id"] for r in response.json()["results"]}
                self.assertNotIn(theirs.pk, ids)
                self.assertIn(mine.pk, ids)

    def test_post_is_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 405)

    def test_status_filter_is_whitelisted(self):
        make_receipt(self.user, n=5)
        make_receipt(self.user, n=6, status=Receipt.Status.REJECTED)
        self.client.force_login(self.user)

        response = self.client.get(self.url, {"status": "rejected"})
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["status"], "rejected")

        response = self.client.get(self.url, {"status": "что-то-левое"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)  # неизвестный статус игнорируется

    def test_payload_shape(self):
        receipt = make_receipt(self.user, n=7, status=Receipt.Status.APPROVED)
        self.client.force_login(self.user)
        item = self.client.get(self.url).json()["results"][0]
        for key in (
            "id",
            "fiscal_number",
            "document_number",
            "amount",
            "purchase_at",
            "created_at",
            "status",
            "status_display",
            "rejection_reason",
        ):
            self.assertIn(key, item)
        self.assertEqual(item["id"], receipt.pk)
        self.assertEqual(item["status_display"], "Обработан")

    def test_winner_badge_label(self):
        make_receipt(self.user, n=8, status=Receipt.Status.APPROVED, is_winner=True)
        self.client.force_login(self.user)
        item = self.client.get(self.url).json()["results"][0]
        self.assertEqual(item["status_display"], "Вы выиграли")
        self.assertEqual(item["status_css"], "winner")

    def test_promo_block_in_response(self):
        from receipts.promo import promo_settings

        self.client.force_login(self.user)
        promo = self.client.get(self.url).json()["promo"]
        self.assertEqual(promo["period_label"], promo_settings().period_label)