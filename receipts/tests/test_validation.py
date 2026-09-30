"""Тесты валидации чека — основная часть задания."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from receipts.forms import ReceiptForm
from receipts.models import Receipt
from receipts.promo import local_to_utc, promo_settings
from receipts.validators import (
    validate_document_number,
    validate_fiscal_number,
    validate_fiscal_signature,
)

from .base import BaseTestCase, make_receipt, valid_payload


class FiscalFieldValidatorsTests(TestCase):
    """Форматы ФН / ФД / ФП."""

    def test_fiscal_number_accepts_12_digits(self):
        self.assertIsNone(validate_fiscal_number("770708183000"))

    def test_fiscal_number_rejects_short_and_long(self):
        for bad in ("7707081830", "7707081830000", "77070818ab00", "", " 77070818300x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_fiscal_number(bad)

    def test_document_number_accepts_digits(self):
        for good in ("1", "0000000123", "1234567890"):
            with self.subTest(good=good):
                self.assertIsNone(validate_document_number(good))

    def test_document_number_rejects_non_digits_and_too_long(self):
        for bad in ("", "12345678901", "12a45", "-1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_document_number(bad)

    def test_fiscal_signature_normalizes_case(self):
        self.assertIsNone(validate_fiscal_signature("3A7B1C"))
        self.assertIsNone(validate_fiscal_signature("3a7b1c"))

    def test_fiscal_signature_rejects_bad_chars(self):
        for bad in ("", "ZZZZ", "3a7b 1c", "3a7b!1c"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_fiscal_signature(bad)


class ReceiptFormValidationTests(BaseTestCase):
    """Серверная валидация формы — она обязательна по заданию."""

    def form(self, payload, user=None):
        return ReceiptForm(payload, user=user or self.user)

    # --- Базовое ---
    def test_valid_payload_is_accepted(self):
        form = self.form(valid_payload())
        self.assertTrue(form.is_valid(), form.errors)

    def test_required_fields(self):
        payload = valid_payload()
        for key in ("fiscal_number", "document_number", "fiscal_signature", "amount", "purchase_date"):
            with self.subTest(missing=key):
                broken = dict(payload)
                broken.pop(key, None)
                form = self.form(broken)
                self.assertFalse(form.is_valid())

    # --- Сумма ---
    def test_amount_below_minimum_rejected(self):
        promo = promo_settings()
        form = self.form(valid_payload(amount=str(promo.min_amount - Decimal("0.01"))))
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_amount_exactly_at_minimum_accepted(self):
        promo = promo_settings()
        form = self.form(valid_payload(amount=str(promo.min_amount)))
        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_accepts_comma_decimal_separator(self):
        form = self.form(valid_payload(amount="1500,50"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount"], Decimal("1500.50"))

    def test_amount_rejects_garbage(self):
        form = self.form(valid_payload(amount="не число"))
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    # --- Период акции ---
    def test_purchase_before_promo_start_rejected(self):
        promo = promo_settings()
        form = self.form(
            valid_payload(purchase_date=(promo.start_date - timedelta(days=1)).strftime("%Y-%m-%d"))
        )
        self.assertFalse(form.is_valid())
        self.assertIn("purchase_date", form.errors)

    def test_purchase_after_promo_end_rejected(self):
        promo = promo_settings()
        form = self.form(
            valid_payload(purchase_date=(promo.end_date + timedelta(days=1)).strftime("%Y-%m-%d"))
        )
        self.assertFalse(form.is_valid())

    def test_first_and_last_day_of_promo_are_inside_the_period(self):
        promo = promo_settings()
        for day in (promo.start_date, promo.end_date):
            with self.subTest(day=day):
                form = self.form(
                    valid_payload(purchase_date=day.strftime("%Y-%m-%d"), purchase_time="00:00")
                )
                self.assertTrue(form.is_valid(), form.errors)

    def test_purchase_time_is_stored_in_promo_timezone(self):
        """Покупка в 00:00 первого дня по времени акции должна пройти."""
        promo = promo_settings()
        form = self.form(
            valid_payload(purchase_date=promo.start_date.strftime("%Y-%m-%d"), purchase_time="00:00")
        )
        self.assertTrue(form.is_valid(), form.errors)
        receipt = form.save()
        self.assertEqual(receipt.purchase_local.hour, 0)
        self.assertEqual(receipt.purchase_local.date(), promo.start_date)

    # --- Уникальность связки ---
    def test_duplicate_receipt_of_same_user_rejected_while_pending(self):
        existing = make_receipt(self.user, n=1)
        payload = valid_payload(n=1)
        form = self.form(payload)
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        self.assertIn("на проверке", " ".join(form.errors["__all__"]))
        # Ровно одно сообщение: штатная проверка уникальности не должна
        # дописывать второе, техническое.
        self.assertEqual(len(form.errors["__all__"]), 1)

    def test_duplicate_receipt_of_other_user_rejected(self):
        make_receipt(self.other, n=2)
        form = self.form(valid_payload(n=2))
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        self.assertEqual(len(form.errors["__all__"]), 1)

    def test_duplicate_does_not_leak_other_users_data(self):
        other = make_receipt(self.other, n=3)
        other.rejection_reason = "Магазин не участвует"
        other.save()
        form = self.form(valid_payload(n=3))
        self.assertFalse(form.is_valid())
        message = " ".join(form.errors["__all__"])
        self.assertEqual(len(form.errors["__all__"]), 1)
        self.assertNotIn("Магазин не участвует", message)
        self.assertNotIn(str(other.pk), message)

    def test_same_fn_different_fd_is_allowed(self):
        make_receipt(self.user, n=4)
        payload = valid_payload(n=4)
        payload["document_number"] = "999999"
        form = self.form(payload)
        self.assertTrue(form.is_valid(), form.errors)

    # --- Повторная отправка отклонённого ---
    def test_rejected_receipt_can_be_resubmitted(self):
        """Спорное место из задания: свой отклонённый чек можно отправить заново."""
        rejected = make_receipt(self.user, n=5, status=Receipt.Status.REJECTED)
        rejected.reject("Некорректный ФП")

        form = self.form(valid_payload(n=5))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.resubmission)

        receipt = form.save()
        self.assertEqual(receipt.pk, rejected.pk)  # та же запись, а не дубль
        self.assertEqual(receipt.status, Receipt.Status.PENDING)
        self.assertEqual(receipt.rejection_reason, "")
        self.assertEqual(receipt.attempts, 2)
        self.assertEqual(Receipt.objects.filter(user=self.user).count(), 1)

    def test_approved_receipt_cannot_be_resubmitted(self):
        approved = make_receipt(self.user, n=6, status=Receipt.Status.APPROVED)
        form = self.form(valid_payload(n=6))
        self.assertFalse(form.is_valid())
        self.assertIn("принят", " ".join(form.errors["__all__"]))

    # --- Статус нового чека ---
    def test_new_receipt_is_always_pending(self):
        form = self.form(valid_payload(n=7))
        self.assertTrue(form.is_valid(), form.errors)
        receipt = form.save()
        self.assertEqual(receipt.status, Receipt.Status.PENDING)
        self.assertEqual(receipt.user, self.user)
        self.assertEqual(receipt.rejection_reason, "")


class PromoPeriodBoundaryTests(TestCase):
    """Границы периода считаются в часовом поясе акции."""

    def test_contains_uses_promo_timezone(self):
        promo = promo_settings()
        self.assertTrue(promo.contains(promo.start_dt))
        self.assertTrue(promo.contains(promo.end_dt))
        self.assertFalse(promo.contains(promo.start_dt - timedelta(seconds=1)))
        self.assertFalse(promo.contains(promo.end_dt + timedelta(seconds=1)))

    def test_boundary_moment_is_utc_independent(self):
        """23:59:59 по времени акции входит в период независимо от пояса сервера."""
        promo = promo_settings()
        naive = datetime.combine(promo.end_date, time(23, 59, 59))
        as_utc = local_to_utc(naive)
        self.assertTrue(promo.contains(as_utc))
        self.assertTrue(promo.contains(as_utc.astimezone(dt_timezone.utc)))