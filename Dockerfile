FROM node:24-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN --mount=type=secret,id=build_ca \
    export http_proxy="${HTTP_PROXY:-}" https_proxy="${HTTPS_PROXY:-}" no_proxy="${NO_PROXY:-}"; \
    task_ca_option=""; \
    if [ -f /run/secrets/build_ca ]; then task_ca_option="-o Acquire::https::CaInfo=/run/secrets/build_ca"; fi; \
    apt-get $task_ca_option update && \
    apt-get $task_ca_option install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock.txt ./backend/requirements.lock.txt
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; pip install --no-cache-dir -r backend/requirements.lock.txt
COPY backend/ ./backend/
COPY scripts/check_database_connection.py ./scripts/check_database_connection.py
COPY scripts/backup.sh ./scripts/backup.sh
COPY --from=frontend /build/frontend/dist ./frontend/dist/
RUN useradd --create-home --uid 10001 tvm && mkdir -p /app/backend/media && chown -R tvm:tvm /app && chmod 0700 /app/backend/media
USER tvm
WORKDIR /app/backend
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--no-control-socket", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
