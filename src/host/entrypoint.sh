#!/bin/sh
set -eu

storage_root="${CHATBOT_STORAGE_PATH:-/app/storage}"
mkdir -p "${storage_root}/documents/originals" \
  "${storage_root}/documents/extracted" \
  "${storage_root}/generated" \
  "${storage_root}/temporary" \
  "${storage_root}/exports"

exec "$@"
