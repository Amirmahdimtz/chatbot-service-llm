FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# Python dependencies: allow a trusted local mirror for Docker builds.
ARG PIP_INDEX_URL=https://pypi.org/simple/
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --timeout 60 --index-url "$PIP_INDEX_URL" -r requirements.txt \
    && groupadd --gid 10001 chatbot \
    && useradd --uid 10001 --gid chatbot --no-create-home chatbot \
    && mkdir -p /app/storage /tmp \
    && chown -R chatbot:chatbot /app/storage

COPY src ./src
# Normalize Windows CRLF in the POSIX entrypoint even if Git checkout used CRLF.
RUN sed -i 's/\r$//' /app/src/host/entrypoint.sh

USER chatbot
EXPOSE 8000
STOPSIGNAL SIGTERM
ENTRYPOINT ["/bin/sh", "/app/src/host/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "src.host.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
