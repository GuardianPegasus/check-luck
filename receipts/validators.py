"""Валидаторы реквизитов чека.

Формат российского фискального чека:
* ФН — 12 цифр (номер налогоплательщика);
* ФД — до 10 цифр (номер фискального документа);
* ФП — до 64 символов, обычно 32 hex-символа (фискальная подпись).
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

FN_LENGTH = 12
FD_MAX_LENGTH = 10
FP_MAX_LENGTH = 64

_FN_RE = re.compile(r"^\d{%d}$" % FN_LENGTH)
_FD_RE = re.compile(r"^\d{1,%d}$" % FD_MAX_LENGTH)
_FP_RE = re.compile(r"^[0-9A-F]{1,%d}$" % FP_MAX_LENGTH)


def validate_fiscal_number(value: str) -> None:
    cleaned = (value or "").strip()
    if not _FN_RE.match(cleaned):
        raise ValidationError(
            _("ФН должен состоять ровно из 12 цифр."),
            code="invalid_fn",
        )


def validate_document_number(value: str) -> None:
    cleaned = (value or "").strip()
    if not _FD_RE.match(cleaned):
        raise ValidationError(
            _("Номер чека (ФД) — от 1 до %(max)d цифр."),
            code="invalid_fd",
            params={"max": FD_MAX_LENGTH},
        )


def validate_fiscal_signature(value: str) -> None:
    cleaned = (value or "").strip().upper()
    if not _FP_RE.match(cleaned):
        raise ValidationError(
            _("ФП — до %(max)d символов, латинские буквы и цифры (0-9, A-F)."),
            code="invalid_fp",
            params={"max": FP_MAX_LENGTH},
        )


def normalize_receipt_fields(data: dict) -> dict:
    """Приводит реквизиты к единому виду (ФП всегда верхний регистр)."""
    for key in ("fiscal_number", "document_number", "fiscal_signature"):
        if key in data and isinstance(data[key], str):
            data[key] = data[key].strip().upper() if key == "fiscal_signature" else data[key].strip()
    return data