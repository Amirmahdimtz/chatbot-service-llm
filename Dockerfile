FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 chatbot \
    && useradd --uid 10001 --gid chatbot --no-create-home chatbot \
    && mkdir -p /app/storage /tmp \
    && chown -R chatbot:chatbot /app/storage

COPY src ./src

USER chatbot
EXPOSE 8000
STOPSIGNAL SIGTERM
ENTRYPOINT ["/bin/sh", "/app/src/host/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "src.host.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
