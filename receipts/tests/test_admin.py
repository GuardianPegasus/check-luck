"""Тесты админки: смена статуса, причина отказа, выгрузка CSV."""
from __future__ import annotations

import csv
import io

from django.contrib import admin
from django.urls import reverse

from receipts.models import Receipt

from .base import BaseTestCase, make_receipt


class ReceiptAdminTests(BaseTestCase):
    def setUp(self):
        self.client.force_login(self.moderator)
        self.list_url = reverse("admin:receipts_receipt_changelist")

    def test_only_staff_sees_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)

    def test_moderator_sees_receipts(self):
        make_receipt(self.user, n=1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "7707081830"[:6])

    def test_approve_action(self):
        receipt = make_receipt(self.user, n=2)
        response = self.client.post(
            self.list_url,
            {"action": "approve_selected", admin.helpers.ACTION_CHECKBOX_NAME: [str(receipt.pk)]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.APPROVED)
        self.assertEqual(receipt.rejection_reason, "")

    def test_reject_requires_reason(self):
        receipt = make_receipt(self.user, n=3)
        response = self.client.post(
            self.list_url,
            {
                "action": "reject_selected",
                admin.helpers.ACTION_CHECKBOX_NAME: [str(receipt.pk)],
                "status": Receipt.Status.REJECTED,
                "rejection_reason": "  ",
                "confirm_marker": "1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.PENDING)

    def test_reject_with_reason(self):
        receipt = make_receipt(self.user, n=4)
        self.client.post(
            self.list_url,
            {
                "action": "reject_selected",
                admin.helpers.ACTION_CHECKBOX_NAME: [str(receipt.pk)],
                "status": Receipt.Status.REJECTED,
                "rejection_reason": "Магазин не участвует в акции",
                "confirm_marker": "1",
            },
            follow=True,
        )
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.REJECTED)
        self.assertEqual(receipt.rejection_reason, "Магазин не участвует в акции")

    def test_csv_export_contains_only_accepted(self):
        approved = make_receipt(self.user, n=5, status=Receipt.Status.APPROVED)
        make_receipt(self.user, n=6, status=Receipt.Status.PENDING)
        make_receipt(self.user, n=7, status=Receipt.Status.REJECTED)

        response = self.client.post(
            self.list_url,
            {
                "action": "export_accepted_csv",
                admin.helpers.ACTION_CHECKBOX_NAME: [str(approved.pk)],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])

        text = response.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ФН"], approved.fiscal_number)
        self.assertEqual(rows[0]["Пользователь"], self.user.get_username())
        self.assertEqual(rows[0]["Статус"], "Принят")

    def test_csv_export_warns_when_nothing_accepted(self):
        pending = make_receipt(self.user, n=8)
        response = self.client.post(
            self.list_url,
            {
                "action": "export_accepted_csv",
                admin.helpers.ACTION_CHECKBOX_NAME: [str(pending.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("text/csv", response.get("Content-Type", ""))