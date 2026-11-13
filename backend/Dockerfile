# Versnq Core backend: the API and (same image, other command) the background worker.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
# The same uv the project is developed with; installs exactly what uv.lock says.
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN chmod +x docker-entrypoint.sh && mkdir -p var/files

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
# 2 workers suit this shared server; raise with more CPU/RAM. Keep 3 processes x
# (DB_POOL_SIZE + DB_MAX_OVERFLOW) under Postgres max_connections (100).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
