"""Typed errors shared by service and API boundaries."""

from __future__ import annotations

from typing import Any


class AgentFlowError(Exception):
    """Base class for expected operational failures."""

    code = "agentflow_error"
    status_code = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(AgentFlowError):
    code = "validation_error"
    status_code = 422


class UnsupportedDocumentError(ValidationError):
    code = "unsupported_document"


class UnsafeDocumentError(ValidationError):
    code = "unsafe_document"


class NotFoundError(AgentFlowError):
    code = "not_found"
    status_code = 404


class ConflictError(AgentFlowError):
    code = "conflict"
    status_code = 409


class DependencyUnavailableError(AgentFlowError):
    code = "dependency_unavailable"
    status_code = 503


class ProviderError(AgentFlowError):
    code = "provider_error"
    status_code = 502


class EvidenceGapError(AgentFlowError):
    code = "evidence_gap"
    status_code = 422
