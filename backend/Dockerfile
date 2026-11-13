# Versnq Core backend: the API and (same image, other command) the background worker.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# requirements.lock.txt is exported from uv.lock (`make requirements`): exact versions and
# checksums. pip with many retries because the server's network to PyPI is patchy.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes --retries 15 --timeout 60 -r requirements.lock.txt
COPY . .
RUN chmod +x docker-entrypoint.sh && mkdir -p var/files

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
# 2 workers suit this shared server; raise with more CPU/RAM. Keep 3 processes x
# (DB_POOL_SIZE + DB_MAX_OVERFLOW) under Postgres max_connections (100).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
