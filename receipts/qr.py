"""Разбор строки из QR-кода кассового чека.

Строка из QR чека выглядит так::

    t=20260101T120000&s=12000.00&fn=7707081830&i=0000000123&fp=3a7b1c...

где:
* ``t`` — дата и время покупки (YYYYMMDDThhmmss, иногда с числом миллисекунд);
* ``s`` — итоговая сумма чека;
* ``fn`` — ФН;
* ``i`` — номер фискального документа (ФД);
* ``fp`` — фискальная подпись (ФП).

Строка может быть обёрнута в ``st=...:`` (передаётся с терминала) или
в URL вида ``https://cash.ya.ru/...?...``. Разбираем оба случая.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, unquote

from .validators import FD_MAX_LENGTH, FN_LENGTH, FP_MAX_LENGTH

# "st=1709:2026-01-01T12:00:00+s=..." — обёртка терминала
_ST_WRAPPER_RE = re.compile(r"^\s*st=\d{0,4}:\s*(?P<inner>.+?)\s*$", re.DOTALL)

# Допускаем разделители, которые встречаются в разных терминалах
_KV_SPLIT_RE = re.compile(r"[&;\s]+")

_TS_RE = re.compile(r"^(?P<d>\d{8})[T ](?P<t>\d{6})(?P<ms>\d{1,3})?$")


class QRParseError(ValueError):
    """Строку не удалось разобрать."""


@dataclass
class ParsedQR:
    """Поля чека, извлечённые из QR-строки."""

    fiscal_number: str = ""
    document_number: str = ""
    fiscal_signature: str = ""
    amount: Decimal | None = None
    purchased_at: datetime | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "fiscal_number": self.fiscal_number,
            "document_number": self.document_number,
            "fiscal_signature": self.fiscal_signature,
            "amount": "" if self.amount is None else format(self.amount, "f"),
            "purchase_date": self.purchased_at.strftime("%Y-%m-%d") if self.purchased_at else "",
            "purchase_time": self.purchased_at.strftime("%H:%M") if self.purchased_at else "",
        }


def _strip_wrapper(raw: str) -> str:
    raw = raw.strip().strip('"')
    # QR может быть вставлен как ссылка
    if "?" in raw and "=" in raw:
        head, _, tail = raw.partition("?")
        if "st=" in head or "cash." in head.lower() or "ofd" in head.lower():
            raw = tail
    m = _ST_WRAPPER_RE.match(raw)
    if m:
        raw = m.group("inner")
    return raw.strip()


def _pairs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in _KV_SPLIT_RE.split(raw):
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        if key and key not in out:
            out[key] = unquote(value.strip())
    # запасной путь — urllib плохо переживает "&amp;" и спецсимволы
    if len(out) < 2:
        for k, v in parse_qsl(raw, keep_blank_values=True):
            k = k.strip().lower()
            if k and k not in out:
                out[k] = v
    return out


def _parse_timestamp(value: str) -> datetime:
    m = _TS_RE.match(value.strip())
    if not m:
        raise QRParseError(f"Не удалось разобрать дату и время покупки: {value!r}")
    return datetime.strptime(m.group("d") + m.group("t"), "%Y%m%d%H%M%S")


def _parse_amount(value: str) -> Decimal:
    cleaned = value.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise QRParseError(f"Не удалось разобрать сумму: {value!r}") from exc


def parse_qr_string(raw: str) -> ParsedQR:
    """Разбирает строку из QR-кода чека.

    Бросает :class:`QRParseError` с понятным сообщением, если строка
    не похожа на QR чека или в ней нет обязательных полей.
    """
    if not raw or not raw.strip():
        raise QRParseError("Пустая строка.")

    cleaned = _strip_wrapper(raw)
    if "=" not in cleaned:
        raise QRParseError(
            "Не похоже на строку из QR-кода чека. Ожидается что-то вроде "
            "t=20260101T120000&s=1200&fn=7707081830&i=0000000123&fp=..."
        )

    data = _pairs(cleaned)

    parsed = ParsedQR()
    parsed.fiscal_number = data.get("fn", "").strip()
    parsed.document_number = data.get("i", "").strip().lstrip("0") or data.get("i", "").strip()
    parsed.fiscal_signature = data.get("fp", "").strip().upper()

    if data.get("s"):
        parsed.amount = _parse_amount(data["s"])
    if data.get("t"):
        parsed.purchased_at = _parse_timestamp(data["t"])

    parsed.extra = {k: v for k, v in data.items() if k not in {"fn", "i", "fp", "s", "t"}}

    missing = []
    if not parsed.fiscal_number:
        missing.append("fn (ФН)")
    if not parsed.document_number:
        missing.append("i (номер чека)")
    if not parsed.fiscal_signature:
        missing.append("fp (ФП)")
    if missing:
        raise QRParseError("В строке нет обязательных полей: " + ", ".join(missing) + ".")

    # Мягкая проверка форматов: длину ФП/ФН не урезаем, но подсказываем проблему
    if len(parsed.fiscal_number) != FN_LENGTH:
        parsed.extra["_warning"] = f"ФН обычно состоит из {FN_LENGTH} цифр, получено {len(parsed.fiscal_number)}."
    if len(parsed.document_number) > FD_MAX_LENGTH:
        parsed.extra["_warning"] = f"Номер чека длиннее {FD_MAX_LENGTH} цифр."
    if len(parsed.fiscal_signature) > FP_MAX_LENGTH:
        parsed.extra["_warning"] = f"ФП длиннее {FP_MAX_LENGTH} символов."

    return parsed