"""Форма регистрации чека.

Валидация на сервере — основная: браузерные подсказки не считаются защитой.
Валидаторы реквизитов описаны в receipts/validators.py, параметры акции
берутся из настроек (receipts/promo.py).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.models import construct_instance
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Receipt
from .promo import format_money, local_to_utc, promo_settings
from .qr import QRParseError, parse_qr_string
from .validators import (
    normalize_receipt_fields,
    validate_document_number,
    validate_fiscal_number,
    validate_fiscal_signature,
)


class CommaDecimalField(forms.DecimalField):
    """Десятичное поле, принимающее и запятую, и точку.

    В макете поле суммы подсказывает формат ``0.00 ₽``, но русский
    пользователь почти всегда вводит «1500,50» — приводим оба варианта.
    """

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        return super().to_python(value)


def receipt_photo_help_text() -> str:
    p = promo_settings()
    return _("%(types)s, до %(size)d МБ") % {"types": p.photo_allowed_types_label, "size": p.photo_max_mb}


class ReceiptForm(forms.ModelForm):
    """Форма регистрации чека.

    Поля формы повторяют макет: ФН, Номер чека (ФД), ФП, Дата покупки, Сумма.
    """

    purchase_date = forms.DateField(
        label="Дата покупки",
        widget=forms.DateInput(attrs={"type": "date", "placeholder": "дд.мм.гггг"}),
    )
    purchase_time = forms.TimeField(
        label="Время покупки",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time", "placeholder": "чч:мм"}),
    )
    amount = CommaDecimalField(
        label="Сумма",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0.00 ₽"}),
    )
    photo = forms.ImageField(
        label="Фото чека",
        required=False,
        help_text=receipt_photo_help_text,
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    class Meta:
        model = Receipt
        fields = ("fiscal_number", "document_number", "fiscal_signature", "amount", "photo")
        widgets = {
            "fiscal_number": forms.TextInput(
                attrs={"inputmode": "numeric", "placeholder": "Введите ФН", "maxlength": 12}
            ),
            "document_number": forms.TextInput(
                attrs={"inputmode": "numeric", "placeholder": "Введите номер чека (ФД)", "maxlength": 10}
            ),
            "fiscal_signature": forms.TextInput(
                attrs={"placeholder": "Введите ФП", "maxlength": 64}
            ),
        }
        error_messages = {
            "fiscal_number": {"required": "Укажите ФН чека."},
            "document_number": {"required": "Укажите номер чека (ФД)."},
            "fiscal_signature": {"required": "Укажите фискальную подпись (ФП)."},
            "amount": {"required": "Укажите сумму чека."},
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.promo = promo_settings()
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " field__input").strip()
            field.widget.attrs.setdefault("aria-describedby", f"id_{name}_error")
        self.order_fields(
            [
                "fiscal_number",
                "document_number",
                "fiscal_signature",
                "purchase_date",
                "purchase_time",
                "amount",
                "photo",
            ]
        )

    # --- Нормализация ----------------------------------------------------
    def clean_fiscal_number(self):
        value = (self.cleaned_data.get("fiscal_number") or "").strip()
        validate_fiscal_number(value)
        return value

    def clean_document_number(self):
        value = (self.cleaned_data.get("document_number") or "").strip()
        validate_document_number(value)
        return value

    def clean_fiscal_signature(self):
        value = (self.cleaned_data.get("fiscal_signature") or "").strip().upper()
        validate_fiscal_signature(value)
        return value

    def clean_amount(self):
        raw = self.cleaned_data.get("amount")
        try:
            value = Decimal(str(raw).replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValidationError("Сумма должна быть числом, например 1200.50") from None
        if value <= 0:
            raise ValidationError("Сумма должна быть больше нуля")
        return value.quantize(Decimal("0.01"))

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return photo
        max_bytes = self.promo.photo_max_bytes
        if photo.size > max_bytes:
            raise ValidationError(
                "Файл слишком большой: максимум %d МБ" % self.promo.photo_max_mb
            )
        content_type = (getattr(photo, "content_type", "") or "").lower()
        if content_type and content_type.split("/")[-1] not in self.promo.photo_allowed_types:
            raise ValidationError(
                "Поддерживаются только файлы: %s" % self.promo.photo_allowed_types_label
            )
        return photo

    # --- Правила акции ---------------------------------------------------
    def clean_purchase_date(self):
        value = self.cleaned_data.get("purchase_date")
        if value is None:
            raise ValidationError("Укажите дату покупки")
        start, end = self.promo.start_date, self.promo.end_date
        if not (start <= value <= end):
            raise ValidationError(
                "Дата покупки должна попадать в период акции: %s" % self.promo.period_label
            )
        return value

    def clean(self):
        cleaned = super().clean()
        # Сначала дубликаты: повторная отправка отклонённого чека не должна
        # съедать квоту под новый чек.
        self._check_duplicate()
        self._check_amount()
        self._check_period()
        self._check_quota()
        return cleaned

    def _check_amount(self) -> None:
        amount = self.cleaned_data.get("amount")
        if amount is None:
            return
        if amount < self.promo.min_amount:
            self.add_error(
                "amount",
                "Минимальная сумма чека по условиям акции — %s" % format_money(self.promo.min_amount),
            )

    def _check_period(self) -> None:
        date_ = self.cleaned_data.get("purchase_date")
        if date_ is None:
            return
        time_ = self.cleaned_data.get("purchase_time") or timezone.datetime.min.time()
        naive = timezone.datetime.combine(date_, time_)
        self.cleaned_data["purchase_at"] = local_to_utc(naive)
        if not self.promo.contains(self.cleaned_data["purchase_at"]):
            self.add_error(
                "purchase_date",
                "Чек должен быть куплен в период акции: %s" % self.promo.period_label,
            )

    def _check_quota(self) -> None:
        limit = self.promo.max_receipts_per_user
        if not limit or self.user is None:
            return
        qs = Receipt.objects.filter(user=self.user)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        # Повторная отправка отклонённого чека не увеличивает число чеков
        resubmission = getattr(self, "_resubmission", None)
        if resubmission is not None and not self.instance.pk:
            qs = qs.exclude(pk=resubmission.pk)
        if qs.count() >= limit:
            self.add_error(None, "Лимит чеков на участника — %d. Вы уже отправили все." % limit)

    def _check_duplicate(self) -> None:
        """Связка ФН + ФД + ФП уже занята?

        Решение по спорному месту из задания: отклонённый СВОЙ чек
        отправлять можно повторно — форма не создаёт дубль, а переводит
        ту же запись обратно в статус «на проверке» и увеличивает счётчик
        попыток. Всё остальное (свой чек на проверке, свой принятый чек,
        чек любого другого участника) — понятная ошибка, а не 500.
        """
        fn = self.cleaned_data.get("fiscal_number")
        fd = self.cleaned_data.get("document_number")
        fp = self.cleaned_data.get("fiscal_signature")
        if not (fn and fd and fp):
            return
        qs = Receipt.objects.filter(fiscal_number=fn, document_number=fd, fiscal_signature=fp)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        existing = qs.first()
        if existing is None:
            return

        if existing.user_id != getattr(self.user, "pk", None):
            # Чеки других участников не показываем и подробностей не раскрываем.
            self._report_duplicate("Такой чек уже зарегистрирован в акции.")
            return

        if existing.status == Receipt.Status.PENDING:
            self._report_duplicate("Этот чек уже отправлен и сейчас на проверке.")
        elif existing.status == Receipt.Status.APPROVED:
            self._report_duplicate("Этот чек уже принят модератором.")
        else:
            self.resubmission = existing

    def _report_duplicate(self, message: str) -> None:
        """Ошибка дубля + флаг, чтобы штатная проверка не добавила вторую."""
        self._duplicate_reported = True
        self.add_error(None, message)

    # --- Сохранение ------------------------------------------------------
    def _post_clean(self):
        # Повторная отправка отклонённого чека: подставляем существующую
        # запись ДО проверки, иначе уникальность ругается на конфликт
        # связки ФН + ФД + ФП с самим собой.
        resubmission = getattr(self, "_resubmission", None)
        if resubmission is not None:
            self.instance = resubmission

        # Делаем то же, что делает стандартная _post_clean(), но без проверки
        # уникальности и ограничений на уровне модели: про дубли мы и так
        # сказали понятным текстом в _check_duplicate(), а второе техническое
        # сообщение про UniqueConstraint пользователю только мешает.
        # На уровне БД ограничение всё равно остаётся — это страховка от гонки
        # двух одновременных запросов (см. ReceiptForm.save()).
        opts = self._meta
        exclude = self._get_validation_exclusions()
        self.instance = construct_instance(self, self.instance, opts.fields, opts.exclude)
        try:
            self.instance.full_clean(
                exclude=exclude, validate_unique=False, validate_constraints=False
            )
        except ValidationError as e:
            self._update_errors(e)

    @property
    def resubmission(self) -> Receipt | None:
        return getattr(self, "_resubmission", None)

    @resubmission.setter
    def resubmission(self, value: Receipt | None) -> None:
        self._resubmission = value

    def save(self, commit: bool = True):
        instance = self.instance

        if self.resubmission is not None:
            # Повторная отправка отклонённого чека: обновляем ту же запись,
            # чтобы не плодить дубли и не ломать историю регистраций.
            instance = self.resubmission
            instance.status = Receipt.Status.PENDING
            instance.rejection_reason = ""
            instance.is_winner = False
            instance.attempts = (instance.attempts or 0) + 1
        elif instance.pk is None:
            instance.user = self.user
            instance.status = Receipt.Status.PENDING

        instance.purchase_at = self.cleaned_data["purchase_at"]

        if commit:
            try:
                with transaction.atomic():
                    instance.save()
                    self.instance = instance
            except IntegrityError:
                # Страховка от гонки двух одновременных отправок
                raise forms.ValidationError(
                    "Такой чек уже зарегистрирован в акции.",
                    code="duplicate",
                ) from None
        return instance

    def clean_receipt_data(self) -> dict:
        return normalize_receipt_fields(dict(self.cleaned_data))


class QRImportForm(forms.Form):
    """Разбор строки из QR-кода на сервере (используется в AJAX-подсказке)."""

    qr = forms.CharField(
        label="Строка из QR-кода",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "t=20260101T120000&s=12000.00&fn=7707081830&i=0000000123&fp=…",
            }
        ),
    )

    def clean_qr(self):
        value = self.cleaned_data.get("qr", "")
        try:
            parsed = parse_qr_string(value)
        except QRParseError as exc:
            raise forms.ValidationError(str(exc)) from None
        self.parsed = parsed
        return value