FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_TIMEZONE=Europe/Moscow \
    DATABASE_PATH=/app/data/assistant.db

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data

VOLUME ["/app/data"]

CMD ["python", "-m", "app.bot.main"]
