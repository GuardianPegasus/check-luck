"""Настройки проекта «Чек на удачу».

Все значимые параметры приходят из окружения (.env), см. .env.example.
Ничего из параметров акции не зашито в коде.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_date(name: str, default: str) -> date:
    raw = os.getenv(name, default).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:  # pragma: no cover - защита от кривой конфигурации
        raise ValueError(
            f"Переменная {name} должна быть в формате ГГГГ-ММ-ДД, получено: {raw!r}"
        ) from exc


def env_decimal(name: str, default: str):
    from decimal import Decimal

    return Decimal(os.getenv(name, default).strip())


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except ValueError:
        return default


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "receipts.apps.ReceiptsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- База данных ---------------------------------------------------------
# По умолчанию PostgreSQL (как в docker compose). Значение DB_ENGINE=sqlite
# позволяет запустить проект без Docker — им пользуются тесты по умолчанию.
if os.getenv("DB_ENGINE", "postgres").lower() == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_NAME", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "luck"),
            "USER": os.getenv("POSTGRES_USER", "luck"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "luck"),
            "HOST": os.getenv("POSTGRES_HOST", "db"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

# --- Пароли ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Локализация ---
# В базе храним UTC, показываем пользователю в часовом поясе акции
# (PROMO_TIMEZONE, см. receipts/promo.py).
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Статика и медиа ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Манифест с хэшами нужен только в продакшене — в DEBUG и в тестах
    # collectstatic не запускается, и {% static %} падал бы с ошибкой.
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "whitenoise.storage.CompressedStaticFilesStorage"
        )
    },
}

# --- Авторизация ---
LOGIN_URL = "receipts:login"
LOGIN_REDIRECT_URL = "receipts:cabinet"
LOGOUT_REDIRECT_URL = "receipts:cabinet"

MESSAGE_TAGS = {
    10: "info",
    20: "info",
    25: "success",
    30: "warning",
    40: "error",
}

# --- Параметры акции (всё из окружения) ---
PROMO_START_DATE = env_date("PROMO_START_DATE", "2026-01-01")
PROMO_END_DATE = env_date("PROMO_END_DATE", "2026-12-31")
PROMO_TIMEZONE = os.getenv("PROMO_TIMEZONE", "Europe/Moscow")
MIN_RECEIPT_AMOUNT = env_decimal("MIN_RECEIPT_AMOUNT", "1000")
# 0 — без ограничения
MAX_RECEIPTS_PER_USER = env_int("MAX_RECEIPTS_PER_USER", 0)

# --- Загрузка фото ---
RECEIPT_PHOTO_MAX_MB = env_int("RECEIPT_PHOTO_MAX_MB", 5)
RECEIPT_PHOTO_ALLOWED_TYPES = tuple(
    t.strip().lower().lstrip(".")
    for t in os.getenv("RECEIPT_PHOTO_ALLOWED_TYPES", "jpg,jpeg,png,webp").split(",")
    if t.strip()
)

# Показываем подробные ошибки 500 только при DEBUG
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_HSTS_SECONDS = 0

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{levelname}] {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}