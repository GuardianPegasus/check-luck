"""Модель чека."""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .promo import format_money, utc_to_local


def receipt_photo_path(instance: "Receipt", filename: str) -> str:
    """Раскладываем фото по дате регистрации: receipts/2026/01/…"""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "jpg").lower()[:5]
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"receipts/{timezone.now():%Y/%m}/{stamp}_{instance.pk or 0}.{ext}"


class Receipt(models.Model):
    """Чек, зарегистрированный участником акции."""

    class Status(models.TextChoices):
        PENDING = "pending", "На проверке"
        APPROVED = "approved", "Принят"
        REJECTED = "rejected", "Отклонён"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="receipts",
        verbose_name="Пользователь",
    )

    # --- Реквизиты чека ---
    fiscal_number = models.CharField(
        "ФН", max_length=12, help_text="12 цифр — номер налогоплательщика"
    )
    document_number = models.CharField(
        "Номер чека (ФД)", max_length=10, help_text="Номер фискального документа"
    )
    fiscal_signature = models.CharField(
        "ФП", max_length=64, help_text="Фискальная подпись, 0-9 и A-F"
    )

    purchase_at = models.DateTimeField("Дата и время покупки")
    amount = models.DecimalField(
        "Сумма",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    # --- Модерация ---
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    rejection_reason = models.TextField("Причина отказа", blank=True, default="")

    # Дополнительный флаг «выиграл» — в макете у принятого чека бывает
    # особый статус «Вы выиграли». Три обязательных статуса из задания
    # при этом остаются нетронутыми.
    is_winner = models.BooleanField("Выиграл", default=False)

    # --- Необязательное фото чека ---
    photo = models.ImageField("Фото чека", upload_to=receipt_photo_path, blank=True, null=True)

    # --- Служебное ---
    created_at = models.DateTimeField("Дата регистрации", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    attempts = models.PositiveIntegerField("Попыток отправки", default=1)

    class Meta:
        verbose_name = "Чек"
        verbose_name_plural = "Чеки"
        ordering = ("-created_at", "-id")
        constraints = [
            # Связка ФН + ФД + ФП уникальна: один и тот же чек нельзя
            # зарегистрировать дважды (ни дважды одним человеком, ни разными).
            models.UniqueConstraint(
                fields=("fiscal_number", "document_number", "fiscal_signature"),
                name="unique_fiscal_receipt",
                violation_error_message=(
                    "Такой чек уже зарегистрирован в акции. "
                    "Проверьте реквизиты или дождитесь проверки ранее отправленного чека."
                ),
            )
        ]
        indexes = [
            models.Index(fields=("user", "-created_at"), name="receipts_user_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Чек №{self.document_number} от {self.purchase_local:%d.%m.%Y} ({self.user})"

    # --- Производные значения -------------------------------------------
    @property
    def purchase_local(self):
        """Дата покупки в часовом поясе акции."""
        return utc_to_local(self.purchase_at)

    @property
    def created_local(self):
        return utc_to_local(self.created_at)

    @property
    def amount_display(self) -> str:
        return format_money(self.amount)

    @property
    def status_label(self) -> str:
        """Подпись статуса в терминах макета."""
        if self.status == self.Status.PENDING:
            return "В обработке"
        if self.status == self.Status.APPROVED:
            return "Вы выиграли" if self.is_winner else "Обработан"
        return "Ошибка"

    @property
    def status_css(self) -> str:
        """CSS-модификатор для бейджа статуса."""
        if self.status == self.Status.PENDING:
            return "pending"
        if self.status == self.Status.APPROVED:
            return "winner" if self.is_winner else "approved"
        return "rejected"

    @property
    def info_text(self) -> str:
        """Текст в колонке «Информация»."""
        if self.status == self.Status.REJECTED:
            return self.rejection_reason or "Чек отклонён модератором"
        if self.status == self.Status.APPROVED and self.is_winner:
            return "Поздравляем, ваш чек выиграл!"
        if self.status == self.Status.APPROVED:
            return "Чек принят и участвует в розыгрыше"
        return "Чек ожидает проверки модератором"

    def approve(self, *, is_winner: bool | None = None) -> None:
        self.status = self.Status.APPROVED
        self.rejection_reason = ""
        if is_winner is not None:
            self.is_winner = is_winner
        self.save(update_fields=["status", "rejection_reason", "is_winner", "updated_at"])

    def reject(self, reason: str) -> None:
        self.status = self.Status.REJECTED
        self.rejection_reason = (reason or "").strip()
        self.save(update_fields=["status", "rejection_reason", "updated_at"])