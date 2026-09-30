"""URL-маршруты приложения."""
from django.urls import path

from . import api, views

app_name = "receipts"

urlpatterns = [
    path("", views.cabinet, name="cabinet"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("receipts/new/", views.register_receipt, name="register"),
    path("receipts/import-qr/", views.import_qr, name="import_qr"),
    path("rules/", views.rules, name="rules"),
    path("api/receipts/", api.receipt_list, name="api_receipts"),
]