FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала только зависимости — слой кэшируется при изменении кода
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Непривилегированный пользователь + папка для БД/логов
RUN useradd -m botuser && mkdir -p /app/data \
    && chown -R botuser:botuser /app
USER botuser

# 8080 — HTTP /health (отключается через HEALTH_PORT=0 в .env)
EXPOSE 8080

CMD ["python", "app.py"]
