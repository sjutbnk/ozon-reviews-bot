FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY . .

RUN pip install --upgrade pip && \
    pip install . && \
    playwright install --with-deps chromium && \
    mkdir -p /app/data /app/storage

CMD ["python", "main.py"]

