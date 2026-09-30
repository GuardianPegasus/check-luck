"""Тесты представлений: кабинет, регистрация чека, правила, авторизация."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from receipts.models import Receipt

from .base import BaseTestCase, make_receipt, valid_payload


class CabinetViewTests(BaseTestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("receipts:cabinet")

    def test_cabinet_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("receipts:login"), response["Location"])

    def test_cabinet_renders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "История чеков")

    def test_cabinet_shows_only_own_receipts(self):
        make_receipt(self.user, n=1)
        make_receipt(self.other, n=2, status=Receipt.Status.APPROVED)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["receipts"]), 1)
        self.assertContains(response, "Чеков внесено")
        self.assertEqual(response.context["total_count"], 1)

    def test_pagination_is_ten_per_page_newest_first(self):
        for i in range(23):
            make_receipt(self.user, n=100 + i)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["receipts"]), 10)
        self.assertEqual(response.context["paginator"].num_pages, 3)

        receipts = list(response.context["receipts"])
        self.assertEqual(receipts, sorted(receipts, key=lambda r: (r.created_at, r.id), reverse=True))

        page2 = self.client.get(self.url, {"page": 2})
        self.assertEqual(len(page2.context["receipts"]), 10)
        page3 = self.client.get(self.url, {"page": 3})
        self.assertEqual(len(page3.context["receipts"]), 3)

        first_ids = {r.id for r in receipts}
        second_ids = {r.id for r in page2.context["receipts"]}
        self.assertFalse(first_ids & second_ids)

    def test_empty_state(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Здесь будет история ваших чеков")

    def test_rejected_reason_is_visible_to_owner(self):
        receipt = make_receipt(self.user, n=3)
        receipt.reject("Товар куплен в магазине, который не участвует в акции")
        response = self.client.get(self.url)
        self.assertContains(response, "который не участвует в акции")


class RegisterReceiptViewTests(BaseTestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("receipts:register")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_renders_form_with_all_mockup_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for field in ("fiscal_number", "document_number", "fiscal_signature", "purchase_date", "amount"):
            self.assertContains(response, f'name="{field}"')

    def test_promo_period_shown_from_settings(self):
        from receipts.promo import promo_settings

        response = self.client.get(self.url)
        self.assertContains(response, promo_settings().period_label)

    def test_post_creates_receipt_and_redirects(self):
        response = self.client.post(self.url, valid_payload(n=10))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Receipt.objects.filter(user=self.user).count(), 1)

    def test_duplicate_returns_200_with_error_not_500(self):
        make_receipt(self.user, n=11)
        response = self.client.post(self.url, valid_payload(n=11))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(Receipt.objects.filter(user=self.user).count(), 1)

    def test_fetch_post_returns_json_success(self):
        response = self.client.post(
            self.url, valid_payload(n=12), HTTP_X_REQUESTED_WITH="Fetch", HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_count"], 1)

    def test_fetch_post_returns_json_errors(self):
        response = self.client.post(
            self.url,
            valid_payload(n=13, amount="10"),
            HTTP_X_REQUESTED_WITH="Fetch",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("amount", payload["errors"])


class QrImportViewTests(BaseTestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("receipts:import_qr")

    def test_parses_qr_string(self):
        qr = "t=20260115T121500&s=12500.00&fn=7707081830&i=0000000123&fp=3A7B1C"
        response = self.client.post(self.url, {"qr": qr})
        self.assertEqual(response.status_code, 200)
        fields = response.json()["fields"]
        self.assertEqual(fields["fiscal_number"], "7707081830")
        self.assertEqual(fields["document_number"], "123")
        self.assertEqual(fields["fiscal_signature"], "3A7B1C")
        self.assertEqual(fields["amount"], "12500.00")
        self.assertEqual(fields["purchase_date"], "2026-01-15")
        self.assertEqual(fields["purchase_time"], "12:15")

    def test_bad_qr_returns_400_with_message(self):
        response = self.client.post(self.url, {"qr": "просто текст"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("qr", response.json()["errors"])

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {"qr": "t=1&s=1&fn=1&i=1&fp=A"})
        self.assertEqual(response.status_code, 302)


class RulesViewTests(BaseTestCase):
    def test_rules_page_shows_period(self):
        from receipts.promo import promo_settings

        response = self.client.get(reverse("receipts:rules"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, promo_settings().period_label)


class TemplateSmokeTests(BaseTestCase):
    """Страницы не должны терять куски разметки.

    Многострочный {# ... #} в Django не комментируется — такой текст попадает
    прямо пользователю. Тест ловит это на любой странице.
    """

    def assert_no_template_garbage(self, response) -> None:
        html = response.content.decode()
        self.assertNotIn("{#", html, "комментарий шаблона попал в вывод")
        self.assertNotIn("{%", html, "тег шаблона попал в вывод")
        self.assertNotIn("#}", html)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_cabinet_renders_clean(self):
        make_receipt(self.user, n=1)
        self.assert_no_template_garbage(self.client.get(reverse("receipts:cabinet")))

    def test_register_page_renders_clean(self):
        response = self.client.get(reverse("receipts:register"))
        self.assert_no_template_garbage(response)
        self.assertContains(response, "Регистрация чека")

    def test_rules_page_renders_clean(self):
        self.assert_no_template_garbage(self.client.get(reverse("receipts:rules")))

    def test_login_page_renders_clean(self):
        self.client.logout()
        self.assert_no_template_garbage(self.client.get(reverse("receipts:login")))

    def test_success_block_is_hidden_on_empty_form(self):
        """Блок успеха есть в разметке, но скрыт — иначе торчит под пустой формой."""
        html = self.client.get(reverse("receipts:register")).content.decode()
        self.assertIn("data-success", html)
        self.assertRegex(html, r"data-success[^>]*\shidden")

    def test_field_order_matches_mockup(self):
        """ФН → ФД → ФП → дата и время → сумма, как в макете."""
        html = self.client.get(reverse("receipts:register")).content.decode()
        positions = [
            html.index('name="%s"' % name)
            for name in (
                "fiscal_number",
                "document_number",
                "fiscal_signature",
                "purchase_date",
                "purchase_time",
                "amount",
            )
        ]
        self.assertEqual(positions, sorted(positions))

    def test_date_and_time_share_one_row(self):
        """Дата и время стоят рядом, а не растянуты на всю ширину по очереди."""
        html = self.client.get(reverse("receipts:register")).content.decode()
        self.assertIn("field__pair", html)