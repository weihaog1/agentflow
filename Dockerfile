# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.0 AS uv-bin

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS python-builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS runtime-base

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 agentflow \
    && useradd --system --uid 10001 --gid agentflow --home-dir /app agentflow

WORKDIR /app
COPY --from=python-builder --chown=agentflow:agentflow /app/.venv /app/.venv
COPY --from=python-builder --chown=agentflow:agentflow /app/migrations /app/migrations
RUN mkdir -p /app/.data/objects \
    && chown -R agentflow:agentflow /app

USER agentflow

FROM runtime-base AS api
EXPOSE 8000
CMD ["agentflow-api"]

FROM runtime-base AS worker
CMD ["agentflow-worker"]
