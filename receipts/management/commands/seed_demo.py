"""Наполняет базу демо-данными: пользователь, модератор и чеки всех статусов.

    python manage.py seed_demo
    python manage.py seed_demo --receipts 30

Пароли демо-пользователей — ``demo12345``, менять перед деплоем.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from receipts.models import Receipt
from receipts.promo import local_to_utc, promo_settings

DEMO_PASSWORD = "demo12345"


class Command(BaseCommand):
    help = "Создаёт демо-пользователей и чеки для локального просмотра."

    def add_arguments(self, parser):
        parser.add_argument("--receipts", type=int, default=14, help="сколько чеков создать")
        parser.add_argument("--password", type=str, default=DEMO_PASSWORD)

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        promo = promo_settings()

        user, created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "nameuser@email.com", "first_name": "Елена", "last_name": "Иванова"},
        )
        if created:
            user.set_password(options["password"])
            user.save(update_fields=["password"])

        moderator, created = User.objects.get_or_create(
            username="moderator",
            defaults={"email": "moderator@email.com", "is_staff": True, "is_superuser": True},
        )
        if created:
            moderator.set_password(options["password"])
            moderator.save(update_fields=["password"])

        span = promo.end_date - promo.start_date
        middle = promo.start_date + span // 2

        statuses = [
            (Receipt.Status.PENDING, "", False),
            (Receipt.Status.APPROVED, "", False),
            (Receipt.Status.APPROVED, "", True),
            (Receipt.Status.REJECTED, "Минимальная стоимость чека должна составлять 1 000 ₽. Подробнее", False),
            (Receipt.Status.REJECTED, "Товар приобретен в магазине, который не участвует в акции. Подробнее", False),
        ]

        created_count = 0
        for i in range(options["receipts"]):
            status, reason, is_winner = statuses[i % len(statuses)]
            purchase_day = middle - timedelta(days=i * 3 % max(span.days, 1))
            receipt = Receipt.objects.create(
                user=user,
                fiscal_number="7707081830%02d" % (i % 100),
                document_number="%06d" % (1000 + i),
                fiscal_signature="%032X" % (0xABCDEF0000 + i),
                purchase_at=local_to_utc(datetime.combine(purchase_day, time(12, 0))),
                amount=Decimal("12000.00") + Decimal(i * 137),
                status=status,
                is_winner=is_winner,
                rejection_reason=reason,
            )
            if status == Receipt.Status.REJECTED:
                receipt.reject(reason)
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: %d чеков. Пользователь demo / moderator, пароль %s"
                % (created_count, options["password"])
            )
        )