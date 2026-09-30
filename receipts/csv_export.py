"""Выгрузка принятых чеков в CSV (бонусная функция)."""
from __future__ import annotations

import csv
from datetime import datetime

from django.http import HttpResponse

from .models import Receipt
from .promo import utc_to_local

COLUMNS = [
    ("id", "ID"),
    ("fiscal_number", "ФН"),
    ("document_number", "ФД"),
    ("fiscal_signature", "ФП"),
    ("purchase_at", "Дата покупки"),
    ("amount", "Сумма"),
    ("status", "Статус"),
    ("is_winner", "Выиграл"),
    ("created_at", "Дата регистрации"),
    ("user", "Пользователь"),
    ("email", "Email"),
    ("rejection_reason", "Причина отказа"),
]


def _row(receipt: Receipt) -> dict:
    return {
        "id": receipt.pk,
        "fiscal_number": receipt.fiscal_number,
        "document_number": receipt.document_number,
        "fiscal_signature": receipt.fiscal_signature,
        "purchase_at": utc_to_local(receipt.purchase_at).strftime("%d.%m.%Y %H:%M"),
        "amount": f"{receipt.amount:.2f}",
        "status": receipt.get_status_display(),
        "is_winner": "да" if receipt.is_winner else "нет",
        "created_at": utc_to_local(receipt.created_at).strftime("%d.%m.%Y %H:%M"),
        "user": receipt.user.get_username(),
        "email": receipt.user.email,
        "rejection_reason": receipt.rejection_reason,
    }


def export_receipts_csv(queryset, filename_prefix="receipts") -> HttpResponse:
    """Отдаёт queryset чеков CSV-файлом с BOM (чтобы Excel понял кодировку)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename_prefix}-{stamp}.csv"'
    # Excel на Windows без BOM открывает кириллицу как кракозябры
    response.write("﻿")

    writer = csv.writer(response)
    writer.writerow([title for _, title in COLUMNS])  # человекочитаемые заголовки
    for receipt in queryset:
        row = _row(receipt)
        writer.writerow([row[key] for key, _ in COLUMNS])
    return response


def export_approved_csv(queryset=None) -> HttpResponse:
    qs = queryset if queryset is not None else Receipt.objects.all()
    return export_receipts_csv(qs.select_related("user"), "receipts-accepted")