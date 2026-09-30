"""Параметры промо-акции, прочитанные из настроек Django (они приходят из .env).

Отдельный модуль, чтобы вся логика «период акции / минимальная сумма»
жила в одном месте и не расползалась по views/forms/validators.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.test.signals import setting_changed
from django.utils import timezone

UTC = dt_timezone.utc

DATE_FORMAT_HUMAN = "%d.%m.%Y"


@dataclass(frozen=True)
class PromoSettings:
    """Снимок параметров акции."""

    start_date: date
    end_date: date
    tz: ZoneInfo
    min_amount: Decimal
    max_receipts_per_user: int
    photo_max_mb: int
    photo_allowed_types: tuple[str, ...]

    # --- Границы периода -------------------------------------------------
    # Начало — 00:00:00 первого дня включительно,
    # конец — 23:59:59.999999 последнего дня включительно.
    # Границы всегда считаются в часовом поясе акции, а не в поясе сервера.
    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start_date, time.min, tzinfo=self.tz)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end_date, time.max, tzinfo=self.tz)

    def contains(self, moment_utc: datetime) -> bool:
        """Проверяет, что момент покупки попадает в период акции.

        ``moment_utc`` — datetime в UTC (так мы храним данные).
        """
        if timezone.is_naive(moment_utc):
            moment_utc = timezone.make_aware(moment_utc, self.tz)
        return self.start_dt <= moment_utc <= self.end_dt

    # --- Прочее ----------------------------------------------------------
    @property
    def period_label(self) -> str:
        return f"{self.start_date.strftime(DATE_FORMAT_HUMAN)} — {self.end_date.strftime(DATE_FORMAT_HUMAN)}"

    @property
    def timezone_label(self) -> str:
        return str(self.tz)

    @property
    def is_open(self) -> bool:
        return self.contains(timezone.now())

    @property
    def photo_max_bytes(self) -> int:
        return self.photo_max_mb * 1024 * 1024

    @property
    def photo_allowed_types_label(self) -> str:
        return ", ".join(self.photo_allowed_types)


@lru_cache(maxsize=1)
def _build() -> PromoSettings:
    try:
        tz = ZoneInfo(settings.PROMO_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover
        tz = ZoneInfo("UTC")
    return PromoSettings(
        start_date=settings.PROMO_START_DATE,
        end_date=settings.PROMO_END_DATE,
        tz=tz,
        min_amount=settings.MIN_RECEIPT_AMOUNT,
        max_receipts_per_user=settings.MAX_RECEIPTS_PER_USER,
        photo_max_mb=settings.RECEIPT_PHOTO_MAX_MB,
        photo_allowed_types=tuple(settings.RECEIPT_PHOTO_ALLOWED_TYPES),
    )


def promo_settings() -> PromoSettings:
    """Возвращает параметры акции.

    Результат кэшируется: менять настройки на лету не нужно, они приходят
    из окружения и фиксируются при старте процесса. В тестах кэш сбрасывается
    через ``override_settings``.
    """
    return _build()


def reset_promo_cache(*args, **kwargs) -> None:
    """Сбрасывает кэш при изменении настроек (``setting_changed``)."""
    _build.cache_clear()


setting_changed.connect(reset_promo_cache)


def local_to_utc(naive_local: datetime) -> datetime:
    """Переводит «наивное» время из формы в UTC, считая его временем акции.

    Так границы периода не «поедут», если у пользователя другой часовой пояс.
    """
    if timezone.is_aware(naive_local):
        return naive_local
    return timezone.make_aware(naive_local, promo_settings().tz).astimezone(UTC)


def utc_to_local(moment_utc: datetime) -> datetime:
    """Переводит UTC в часовой пояс акции — для показа пользователю."""
    tz = promo_settings().tz
    if timezone.is_naive(moment_utc):
        moment_utc = timezone.make_aware(moment_utc, UTC)
    return moment_utc.astimezone(tz)


def format_money(amount: Decimal | int | float | str) -> str:
    """1234.5 -> '1 234,50 ₽'"""
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    return f"{value:,.2f} ₽".replace(",", " ").replace(".", ",")