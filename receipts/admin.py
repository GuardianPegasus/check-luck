"""Админка: модератор работает через стандартный интерфейс Django."""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from .csv_export import export_receipts_csv
from .models import Receipt
from .promo import promo_settings


class RejectReceiptForm(forms.Form):
    """Форма отказа: статус + причина (причина обязательна)."""

    status = forms.ChoiceField(choices=Receipt.Status.choices, initial=Receipt.Status.REJECTED)
    rejection_reason = forms.CharField(
        label="Причина отказа",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Обязательно, если статус — «Отклонён». Показывается в кабинете.",
    )
    is_winner = forms.BooleanField(label="Отметить как выигравший", required=False, initial=False)

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        reason = (cleaned.get("rejection_reason") or "").strip()
        if status == Receipt.Status.REJECTED and not reason:
            self.add_error("rejection_reason", "Укажите причину отказа — её увидит пользователь.")
        if status == Receipt.Status.APPROVED and reason:
            cleaned["rejection_reason"] = ""
        return cleaned


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "user",
        "fiscal_number",
        "document_number",
        "amount_display",
        "status_badge",
        "is_winner",
        "has_photo",
    )
    list_filter = ("status", "is_winner", "created_at")
    search_fields = ("fiscal_number", "document_number", "fiscal_signature", "user__username", "user__email")
    date_hierarchy = "created_at"
    list_select_related = ("user",)
    ordering = ("-created_at",)
    actions = ("approve_selected", "reject_selected", "export_accepted_csv")

    fieldsets = (
        (None, {"fields": ("user", ("fiscal_number", "document_number", "fiscal_signature"))}),
        ("Покупка", {"fields": ("purchase_at", "amount")}),
        ("Модерация", {"fields": ("status", "rejection_reason", "is_winner")}),
        ("Служебное", {"fields": ("attempts", "created_at", "updated_at"), "classes": ("collapse",)}),
        ("Вложение", {"fields": ("photo",)}),
    )
    readonly_fields = ("attempts", "created_at", "updated_at")

    # --- Отображение -----------------------------------------------------
    @admin.display(description="Сумма")
    def amount_display(self, obj):
        return obj.amount_display

    @admin.display(description="Статус")
    def status_badge(self, obj):
        colors = {
            "pending": "#EBB917",
            "approved": "#37CD1A",
            "rejected": "#F04D4D",
            "winner": "#524FE5",
        }
        css = obj.status_css
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;border-radius:12px;'
            'font-size:11px;font-weight:600;white-space:nowrap;">{}</span>',
            colors.get(css, "#787E91"),
            "#FFFFFF" if css in {"approved", "rejected", "winner"} else colors.get(css, "#3E4552"),
            obj.status_label,
        )

    @admin.display(boolean=True, description="Фото")
    def has_photo(self, obj):
        return bool(obj.photo)

    # --- Действия --------------------------------------------------------
    @admin.action(description="Принять выбранные чеки")
    def approve_selected(self, request, queryset):
        updated = 0
        for receipt in queryset:
            receipt.approve()
            updated += 1
        self.message_user(request, f"Принято чеков: {updated}", messages.SUCCESS)

    @admin.action(description="Отклонить выбранные чеки (с причиной)")
    def reject_selected(self, request, queryset):
        # Два шага: сначала показываем форму с причиной, потом применяем.
        # Второй шаг отличается наличием confirm_marker в POST.
        confirm_marker = request.POST.get("confirm_marker")
        if not confirm_marker:
            return self._show_reject_form(request, queryset)

        form = RejectReceiptForm(request.POST)
        if not form.is_valid():
            self.message_user(request, "Проверьте форму: причина обязательна.", messages.ERROR)
            return self._show_reject_form(request, queryset, form)
        reason = form.cleaned_data.get("rejection_reason", "")
        status = form.cleaned_data["status"]
        is_winner = form.cleaned_data.get("is_winner", False)
        updated = 0
        for receipt in queryset:
            if status == Receipt.Status.APPROVED:
                receipt.approve(is_winner=is_winner)
            else:
                receipt.reject(reason)
            updated += 1
        self.message_user(request, f"Обновлено чеков: {updated}", messages.SUCCESS)
        return None

    def _show_reject_form(self, request, queryset, form=None):
        from django.template.response import TemplateResponse

        opts = self.model._meta
        context = {
            **self.admin_site.each_context(request),
            "title": "Отклонить чеки",
            "opts": opts,
            "queryset": queryset,
            "form": form or RejectReceiptForm(initial={"status": Receipt.Status.REJECTED}),
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "media": self.media,
        }
        return TemplateResponse(request, "admin/receipts/reject_form.html", context)

    @admin.action(description="Выгрузить в CSV (только принятые)")
    def export_accepted_csv(self, request, queryset):
        accepted = queryset.filter(status=Receipt.Status.APPROVED).select_related("user")
        if not accepted.exists():
            self.message_user(request, "Среди выбранных нет принятых чеков.", messages.WARNING)
            return None
        return export_receipts_csv(accepted, "receipts-accepted")

    # --- Прочее ----------------------------------------------------------
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        promo = promo_settings()
        extra_context["promo_period"] = promo.period_label
        extra_context["status_counts"] = (
            Receipt.objects.values("status").annotate(n=Count("id")).order_by("status")
        )
        return super().changelist_view(request, extra_context)