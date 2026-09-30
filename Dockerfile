FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Системные библиотеки, нужные Pillow
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo libpng16-16 libwebp7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Каталог для загруженных фото и собранной статики
RUN mkdir -p /app/media /app/staticfiles

EXPOSE 8000

# collectstatic выполняется при старте контейнера (см. entrypoint в compose)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]