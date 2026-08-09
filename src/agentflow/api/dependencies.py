"""FastAPI dependency accessors."""

from __future__ import annotations

from fastapi import Request

from agentflow.container import Container
from agentflow.errors import DependencyUnavailableError


def get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise DependencyUnavailableError("application dependencies are not ready")
    return container
