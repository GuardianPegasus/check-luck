"""Общие фикстуры для тестов."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from receipts.models import Receipt
from receipts.promo import local_to_utc, promo_settings


def unique_receipt_fields(n: int = 0) -> dict:
    """Гарантированно уникальная связка ФН + ФД + ФП."""
    return {
        "fiscal_number": "7707081830%02d" % (n % 100),
        "document_number": "%06d" % (1000 + n),
        "fiscal_signature": ("%032X" % (0xABCDEF0000 + n)),
    }


def valid_payload(n: int = 0, **overrides) -> dict:
    """Готовый набор данных формы, проходящий валидацию."""
    promo = promo_settings()
    middle = promo.start_date + (promo.end_date - promo.start_date) / 2
    payload = {
        **unique_receipt_fields(n),
        "purchase_date": middle.strftime("%Y-%m-%d"),
        "purchase_time": "12:00",
        "amount": "1500.00",
    }
    payload.update(overrides)
    return payload


def make_receipt(user, n: int = 0, status: str = Receipt.Status.PENDING, **overrides) -> Receipt:
    promo = promo_settings()
    middle = promo.start_date + (promo.end_date - promo.start_date) / 2
    fields = {
        "user": user,
        **unique_receipt_fields(n),
        "purchase_at": local_to_utc(datetime.combine(middle, time(12, 0))),
        "amount": Decimal("1500.00"),
        "status": status,
    }
    fields.update(overrides)
    return Receipt.objects.create(**fields)


class BaseTestCase(TestCase):
    """Общие пользователи для тестов."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="elena", email="elena@example.com", password="pass-12345", first_name="Елена"
        )
        cls.other = User.objects.create_user(
            username="ivan", email="ivan@example.com", password="pass-12345"
        )
        cls.moderator = User.objects.create_user(
            username="mod", email="mod@example.com", password="pass-12345", is_staff=True
        )
        # Модератору нужны права на модель чека, иначе админка отдаёт 403
        cls.moderator.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="receipts", content_type__model="receipt"
            )
        )