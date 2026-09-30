"""Тесты разбора строки из QR-кода."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase

from receipts.qr import QRParseError, parse_qr_string


class ParseQrStringTests(SimpleTestCase):
    def test_plain_string(self):
        parsed = parse_qr_string(
            "t=20260115T121500&s=12500.00&fn=7707081830&i=0000000123&fp=3A7B1C"
        )
        self.assertEqual(parsed.fiscal_number, "7707081830")
        self.assertEqual(parsed.document_number, "123")
        self.assertEqual(parsed.fiscal_signature, "3A7B1C")
        self.assertEqual(parsed.amount, Decimal("12500.00"))
        self.assertEqual(parsed.purchased_at, datetime(2026, 1, 15, 12, 15, 0))

    def test_wrapped_with_st_prefix(self):
        parsed = parse_qr_string(
            'st=1709:2026-01-15T12:15:00s=12500&fn=7707081830&i=123&fp=3A7B1C'
        )
        self.assertEqual(parsed.fiscal_number, "7707081830")

    def test_quoted_string(self):
        parsed = parse_qr_string('"t=20260115T121500&s=12500.00&fn=7707081830&i=123&fp=3A7B1C"')
        self.assertEqual(parsed.document_number, "123")

    def test_url_wrapped(self):
        parsed = parse_qr_string(
            "https://cash.example.ru/check?t=20260115T121500&s=100&fn=7707081830&i=123&fp=AB12"
        )
        self.assertEqual(parsed.fiscal_number, "7707081830")

    def test_lowercase_signature_is_uppercased(self):
        parsed = parse_qr_string("t=20260115T121500&s=1&fn=7707081830&i=123&fp=3a7b1c")
        self.assertEqual(parsed.fiscal_signature, "3A7B1C")

    def test_amount_with_comma(self):
        parsed = parse_qr_string("t=20260115T121500&s=1250,50&fn=7707081830&i=123&fp=AB")
        self.assertEqual(parsed.amount, Decimal("1250.50"))

    def test_milliseconds_in_timestamp(self):
        parsed = parse_qr_string("t=20260115T121500123&s=1&fn=7707081830&i=123&fp=AB")
        self.assertEqual(parsed.purchased_at, datetime(2026, 1, 15, 12, 15, 0))

    def test_extra_fields_are_kept(self):
        parsed = parse_qr_string("t=20260115T121500&s=1&fn=7707081830&i=123&fp=AB&n=Иван&p=1")
        self.assertEqual(parsed.extra.get("n"), "Иван")

    def test_missing_required_field_raises(self):
        with self.assertRaises(QRParseError) as ctx:
            parse_qr_string("t=20260115T121500&s=1&i=123&fp=AB")
        self.assertIn("fn", str(ctx.exception))

    def test_garbage_raises(self):
        for bad in ("", "   ", "просто текст", "t=20260115T121500&s=1"):
            with self.subTest(bad=bad):
                with self.assertRaises(QRParseError):
                    parse_qr_string(bad)

    def test_bad_timestamp_raises(self):
        with self.assertRaises(QRParseError):
            parse_qr_string("t=вчера&s=1&fn=7707081830&i=123&fp=AB")

    def test_bad_amount_raises(self):
        with self.assertRaises(QRParseError):
            parse_qr_string("t=20260115T121500&s=много&fn=7707081830&i=123&fp=AB")

    def test_warning_when_fn_length_is_unusual(self):
        parsed = parse_qr_string("t=20260115T121500&s=1&fn=77070818&i=123&fp=AB")
        self.assertIn("_warning", parsed.extra)

    def test_as_dict_shape(self):
        payload = parse_qr_string(
            "t=20260115T121500&s=12500.00&fn=7707081830&i=0000000123&fp=3A7B1C"
        ).as_dict()
        self.assertEqual(
            set(payload),
            {"fiscal_number", "document_number", "fiscal_signature", "amount", "purchase_date", "purchase_time"},
        )