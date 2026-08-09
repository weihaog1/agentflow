"""Prometheus metrics with bounded label cardinality."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "agentflow_http_requests_total",
    "HTTP requests handled by route template.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "agentflow_http_request_duration_seconds",
    "HTTP request duration by route template.",
    ("method", "route"),
)
INGESTION_JOBS = Counter(
    "agentflow_ingestion_jobs_total",
    "Ingestion job outcomes.",
    ("outcome",),
)
INGESTION_STAGE_DURATION = Histogram(
    "agentflow_ingestion_stage_duration_seconds",
    "Ingestion stage duration.",
    ("stage",),
)
WORKFLOW_RUNS = Counter(
    "agentflow_workflow_runs_total",
    "Workflow run outcomes.",
    ("workflow", "outcome", "cached"),
)
WORKFLOW_DURATION = Histogram(
    "agentflow_workflow_duration_seconds",
    "Workflow run duration.",
    ("workflow",),
)
WORKER_ACTIVE = Gauge("agentflow_worker_active", "Whether the process worker loop is active.")


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
