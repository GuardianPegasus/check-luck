"""Тесты модели и вспомогательных функций."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from receipts.models import Receipt
from receipts.promo import format_money, local_to_utc, promo_settings, utc_to_local

from .base import BaseTestCase, make_receipt, unique_receipt_fields


class ReceiptModelTests(BaseTestCase):
    def test_status_labels_match_mockup(self):
        pending = make_receipt(self.user, n=1)
        self.assertEqual(pending.status_label, "В обработке")
        self.assertEqual(pending.status_css, "pending")

        approved = make_receipt(self.user, n=2, status=Receipt.Status.APPROVED)
        self.assertEqual(approved.status_label, "Обработан")
        self.assertEqual(approved.status_css, "approved")

        winner = make_receipt(self.user, n=3, status=Receipt.Status.APPROVED, is_winner=True)
        self.assertEqual(winner.status_label, "Вы выиграли")
        self.assertEqual(winner.status_css, "winner")

        rejected = make_receipt(self.user, n=4, status=Receipt.Status.REJECTED)
        self.assertEqual(rejected.status_label, "Ошибка")
        self.assertEqual(rejected.status_css, "rejected")

    def test_rejection_reason_in_info(self):
        receipt = make_receipt(self.user, n=5)
        receipt.reject("Товар приобретён в магазине, который не участвует в акции")
        self.assertIn("не участвует", receipt.info_text)

    def test_approve_clears_reason(self):
        receipt = make_receipt(self.user, n=6, status=Receipt.Status.REJECTED, rejection_reason="было")
        receipt.approve()
        self.assertEqual(receipt.rejection_reason, "")
        self.assertEqual(receipt.status, Receipt.Status.APPROVED)

    def test_database_rejects_duplicate_triplet(self):
        make_receipt(self.user, n=7)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Receipt.objects.create(
                    user=self.other,
                    **unique_receipt_fields(7),
                    purchase_at=make_receipt(self.user, n=7).purchase_at,
                    amount=Decimal("1500.00"),
                )

    def test_ordering_is_newest_first(self):
        first = make_receipt(self.user, n=8)
        second = make_receipt(self.user, n=9)
        self.assertEqual(list(Receipt.objects.all()), [second, first])

    def test_amount_display_uses_rubles_format(self):
        receipt = make_receipt(self.user, n=10, amount=Decimal("12500.50"))
        self.assertEqual(receipt.amount_display, "12 500,50 ₽")

    def test_purchase_local_converts_to_promo_timezone(self):
        promo = promo_settings()
        naive = datetime.combine(promo.start_date, time(3, 0))
        receipt = make_receipt(
            self.user, n=11, purchase_at=local_to_utc(naive)
        )
        self.assertEqual(receipt.purchase_local.date(), promo.start_date)
        self.assertEqual(receipt.purchase_local.hour, 3)


class FormattingTests(TestCase):
    def test_format_money(self):
        self.assertEqual(format_money(Decimal("0")), "0,00 ₽")
        self.assertEqual(format_money(Decimal("1000")), "1 000,00 ₽")
        self.assertEqual(format_money(Decimal("1234567.891")), "1 234 567,89 ₽")

    def test_utc_to_local_roundtrip(self):
        promo = promo_settings()
        moment = local_to_utc(datetime(2026, 6, 15, 18, 30))
        self.assertEqual(utc_to_local(moment), moment.astimezone(promo.tz))