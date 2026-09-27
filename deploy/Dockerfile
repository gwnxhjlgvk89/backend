FROM docker.io/library/python:3.11.15-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY club ./club
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home club && mkdir -p /data /metrics && chown club:club /data /metrics
COPY deploy/entrypoint.sh /app/entrypoint.sh
USER club
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["uvicorn", "club.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--no-access-log"]
