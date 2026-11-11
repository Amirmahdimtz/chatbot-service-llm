FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# Python dependencies: allow a trusted local mirror for Docker builds.
ARG PIP_INDEX_URL=https://pypi.org/simple/
# Local legacy-Word conversion and Persian OCR, no cloud document service.
# Optional mirrors and bounded retries prevent indefinite Debian repository stalls.
ARG APT_DEBIAN_MIRROR_URL=https://deb.debian.org/debian
ARG APT_SECURITY_MIRROR_URL=https://deb.debian.org/debian-security
RUN set -eu; \
    for mirror in "$APT_DEBIAN_MIRROR_URL" "$APT_SECURITY_MIRROR_URL"; do \
        case "$mirror" in https://*|http://*) ;; *) echo "Invalid APT mirror URL" >&2; exit 2 ;; esac; \
        case "$mirror" in *[!a-zA-Z0-9:/._-]*) echo "Invalid APT mirror URL" >&2; exit 2 ;; esac; \
    done; \
    sed -i \
        -e "s|http://deb.debian.org/debian-security|$APT_SECURITY_MIRROR_URL|g" \
        -e "s|http://deb.debian.org/debian|$APT_DEBIAN_MIRROR_URL|g" \
        /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update; \
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
        install -y --no-install-recommends \
        libreoffice-writer tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng; \
    rm -rf /var/lib/apt/lists/*
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
