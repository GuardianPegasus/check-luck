"""Тесты админки: смена статуса, причина отказа, выгрузка CSV."""
from __future__ import annotations

import csv
import io
import re

from django.contrib import admin
from django.urls import reverse

from receipts.admin import ReceiptAdmin
from receipts.models import Receipt

from .base import BaseTestCase, make_receipt


def _channels(hex_color: str) -> tuple[float, float, float]:
    """Относительная яркость по WCAG — чтобы поймать нечитаемый текст."""
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    channels = []
    for value in (r, g, b):
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """Контрастность двух цветов по WCAG: 1 — неразличимы, 21 — макс."""
    lighter, darker = sorted((_channels(first), _channels(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


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


class AdminStatusBadgeTests(BaseTestCase):
    """Бейдж статуса в админке обязан быть читаемым.

    Регрессия: текст бейджа брался из того же словаря, что и фон, и у
    «В обработке» получался жёлтый текст на жёлтом фоне — статус не читался.

    Контраст проверен по WCAG: для 11px-текста норма — 4.5. Белый на жёлтом
    даёт 1.83, на зелёном 2.12, поэтому там тёмный текст.
    """

    # Ожидаемое соответствие: фон и цвет текста по статусам.
    # Меняя цвета, правьте тут — тест не даст сделать статус нечитаемым.
    EXPECTED = {
        "В обработке": ("#EBB917", "#3E4552"),
        "Обработан": ("#37CD1A", "#3E4552"),
        "Ошибка": ("#F04D4D", "#FFFFFF"),
        "Вы выиграли": ("#524FE5", "#FFFFFF"),
    }

    def setUp(self):
        super().setUp()
        self.client.force_login(self.moderator)

    @staticmethod
    def parse(markup):
        background = re.search(r"background:\s*(#[0-9A-Fa-f]{6})", markup).group(1)
        color = re.search(r"color:\s*(#[0-9A-Fa-f]{6})", markup).group(1)
        label = re.search(r'white-space:nowrap;">([^<]+)</span>', markup).group(1)
        return background.upper(), color.upper(), label

    def badges(self):
        """{подпись: (фон, цвет текста)} — ключ совпадает с показанной подписью."""
        receipt_admin = ReceiptAdmin(Receipt, admin.site)
        winner = make_receipt(self.user, n=24, status=Receipt.Status.APPROVED, is_winner=True)
        parsed = [
            self.parse(receipt_admin.status_badge(receipt))
            for receipt in (
                make_receipt(self.user, n=21, status=Receipt.Status.PENDING),
                make_receipt(self.user, n=22, status=Receipt.Status.APPROVED),
                make_receipt(self.user, n=23, status=Receipt.Status.REJECTED),
                winner,
            )
        ]
        return {_label: (background, color) for background, color, _label in parsed}

    def test_badge_colors_match_expected(self):
        for label, (background, color) in self.badges().items():
            with self.subTest(status=label):
                self.assertEqual((background, color), self.EXPECTED[label])

    def test_every_badge_is_readable(self):
        for label, (background, color) in self.badges().items():
            with self.subTest(status=label):
                self.assertNotEqual(
                    background, color, "текст бейджа совпал с фоном — статус не читается"
                )
                self.assertGreaterEqual(
                    contrast(background, color),
                    3.0,
                    "контраст текста и фона ниже минимума для 11px",
                )

    def test_light_badges_meet_wcag_aa(self):
        """На светлых фонах текст обязан проходить AA для мелкого шрифта."""
        for label, (background, color) in self.badges().items():
            if background not in {"#EBB917", "#37CD1A"}:
                continue
            with self.subTest(status=label):
                self.assertGreaterEqual(contrast(background, color), 4.5)

    def test_badge_label_matches_cabinet_label(self):
        """Подпись в админке и в кабинете не должна разъезжаться."""
        receipt_admin = ReceiptAdmin(Receipt, admin.site)
        for n, status in enumerate(
            [Receipt.Status.PENDING, Receipt.Status.APPROVED, Receipt.Status.REJECTED], start=31
        ):
            receipt = make_receipt(self.user, n=n, status=status)
            with self.subTest(status=status):
                _, _, shown = self.parse(receipt_admin.status_badge(receipt))
                self.assertEqual(shown, receipt.status_label)

    def test_all_statuses_covered(self):
        """Каждый статус из модели попал в бейджи — новый статус не забудем."""
        self.assertEqual(
            set(self.badges()),
            {
                Receipt(status=Receipt.Status.PENDING).status_label,
                Receipt(status=Receipt.Status.APPROVED).status_label,
                Receipt(status=Receipt.Status.REJECTED).status_label,
                Receipt(status=Receipt.Status.APPROVED, is_winner=True).status_label,
            },
        )