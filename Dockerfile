# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.0 AS uv-bin

FROM python:3.15.0rc1-slim-trixie@sha256:858b8c9b2c764d1a3076e2c2ed64fb3f76ca2ec068ec81c1c059d3a5fcc1088e AS python-builder

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

FROM python:3.15.0rc1-slim-trixie@sha256:858b8c9b2c764d1a3076e2c2ed64fb3f76ca2ec068ec81c1c059d3a5fcc1088e AS runtime-base

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
