"""Представления приложения."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import QRImportForm, ReceiptForm
from .models import Receipt
from .promo import promo_settings

PAGE_SIZE = 10


# --- Личный кабинет -----------------------------------------------------
@login_required
def cabinet(request):
    """Список чеков текущего пользователя: от новых к старым, по 10 на страницу."""
    receipts = (
        Receipt.objects.filter(user=request.user)
        .select_related("user")
        .order_by("-created_at", "-id")
    )
    statuses = request.GET.getlist("status")
    if statuses:
        receipts = receipts.filter(status__in=statuses)

    paginator = Paginator(receipts, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    counts = {
        "all": Receipt.objects.filter(user=request.user).count(),
        "pending": Receipt.objects.filter(user=request.user, status=Receipt.Status.PENDING).count(),
        "approved": Receipt.objects.filter(user=request.user, status=Receipt.Status.APPROVED).count(),
        "rejected": Receipt.objects.filter(user=request.user, status=Receipt.Status.REJECTED).count(),
    }

    return render(
        request,
        "receipts/cabinet.html",
        {
            "page_obj": page,
            "paginator": paginator,
            "receipts": page.object_list,
            "total_count": counts["all"],
            "counts": counts,
            "promo": promo_settings(),
            "active_statuses": statuses,
        },
    )


# --- Регистрация чека ---------------------------------------------------
@login_required
def register_receipt(request):
    """Форма регистрации чека: GET — форма, POST — приём данных.

    Ответ отдаётся JSON, если клиент просит об этом (fetch + заголовок
    ``X-Requested-With``), иначе — обычная страница без перезагрузки
    (fallback, если JS недоступен).
    """
    promo = promo_settings()
    form = ReceiptForm(request.POST or None, request.FILES or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        receipt = form.save()
        payload = {
            "ok": True,
            # Заголовок экрана успеха — как в макете
            "message": "Ваш чек загружен",
            "detail": "Мы уже начали анализировать ваши покупки. Это займёт всего пару секунд.",
            "receipt_id": receipt.pk,
            "is_resubmission": form.resubmission is not None,
            "total_count": Receipt.objects.filter(user=request.user).count(),
            "redirect": reverse("receipts:cabinet"),
        }
        if _wants_json(request):
            return JsonResponse(payload, status=201)
        messages.success(
            request,
            "Чек отправлен" if not form.resubmission else "Чек отправлен повторно",
        )
        return redirect("receipts:cabinet")

    if request.method == "POST":
        if _wants_json(request):
            return JsonResponse({"ok": False, "errors": _form_errors(form)}, status=400)
        messages.error(request, "Проверьте заполнение формы.")

    return render(
        request,
        "receipts/register.html",
        {
            "form": form,
            "promo": promo,
            "page_title": "Регистрация чека",
        },
    )


def _wants_json(request) -> bool:
    return (
        request.headers.get("X-Requested-With") == "Fetch"
        or request.headers.get("Accept", "").startswith("application/json")
        or request.headers.get("Content-Type", "").startswith("application/json")
    )


def _form_errors(form) -> dict:
    """Ошибки формы в виде {field: [сообщения, ...]} + общий список."""
    errors = {name: [str(m) for m in msgs] for name, msgs in form.errors.items()}
    errors.setdefault("__all__", [])
    return errors


# --- Разбор QR-строки (бонус) ------------------------------------------
@login_required
@require_POST
def import_qr(request):
    """Разбирает строку из QR-кода и отдаёт значения для автозаполнения формы."""
    form = QRImportForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": _form_errors(form)}, status=400)
    parsed = form.parsed
    payload = {"ok": True, "fields": parsed.as_dict()}
    if "_warning" in parsed.extra:
        payload["warning"] = parsed.extra["_warning"]
    return JsonResponse(payload)


# --- Правила акции ------------------------------------------------------
def rules(request):
    promo = promo_settings()
    return render(request, "receipts/rules.html", {"promo": promo})


# --- Авторизация --------------------------------------------------------
class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    http_method_names = ["get", "post"]