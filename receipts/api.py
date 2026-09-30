"""JSON API приложения.

Единственный эндпоинт из задания — ``GET /api/receipts/``: чеки
текущего пользователя. Чужие чеки нельзя получить НИ ПРИ КАКИХ параметрах
запроса, поэтому:

* выборка всегда строится как ``Receipt.objects.filter(user=request.user)``;
* пользователь не может подменить объект queryset через GET-параметры —
  допускается только фильтр по статусу из белого списка;
* анонимный запрос получает 401 (а не 403 и не данные).
"""
from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Receipt
from .promo import promo_settings

ALLOWED_STATUSES = {choice for choice, _ in Receipt.Status.choices}


def serialize(receipt: Receipt) -> dict:
    return {
        "id": receipt.pk,
        "fiscal_number": receipt.fiscal_number,
        "document_number": receipt.document_number,
        "amount": str(receipt.amount),
        "amount_display": receipt.amount_display,
        "purchase_at": receipt.purchase_local.strftime("%d.%m.%Y %H:%M"),
        "created_at": receipt.created_local.strftime("%d.%m.%Y %H:%M"),
        "status": receipt.status,
        "status_display": receipt.status_label,
        "status_css": receipt.status_css,
        "is_winner": receipt.is_winner,
        "rejection_reason": receipt.rejection_reason,
        "info": receipt.info_text,
        "has_photo": bool(receipt.photo),
    }


@require_GET
def receipt_list(request):
    """Чеки текущего пользователя в JSON."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"detail": "Требуется авторизация.", "code": "not_authenticated"},
            status=401,
        )

    qs = Receipt.objects.filter(user=request.user).order_by("-created_at", "-id")

    # Параметры запроса НЕ позволяют выбрать чужого пользователя или чужой чек.
    # Из них уважается только status — и только из белого списка.
    requested = request.GET.getlist("status")
    statuses = [s for s in requested if s in ALLOWED_STATUSES]
    if statuses:
        qs = qs.filter(status__in=statuses)

    limit_param = request.GET.get("limit")
    if limit_param and limit_param.isdigit():
        qs = qs[: max(1, min(int(limit_param), 200))]

    promo = promo_settings()
    return JsonResponse(
        {
            "count": qs.count() if qs.query.is_sliced else len(qs),
            "promo": {
                "start_date": promo.start_date.isoformat(),
                "end_date": promo.end_date.isoformat(),
                "period_label": promo.period_label,
                "min_amount": str(promo.min_amount),
            },
            "results": [serialize(r) for r in qs],
        }
    )