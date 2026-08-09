"""Canonical workflow input normalization shared by storage and execution."""

from __future__ import annotations

from typing import Any

from agentflow.cache.keys import normalize_text
from agentflow.domain import WorkflowType
from agentflow.errors import ValidationError


def normalize_workflow_input(
    workflow: WorkflowType,
    raw: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if workflow == WorkflowType.QUESTION:
        question = normalize_text(str(raw.get("question", "")))
        if not question:
            raise ValidationError("question cannot be empty")
        return {"question": question}, question
    if workflow == WorkflowType.COMPARE:
        focus = normalize_text(str(raw.get("focus") or "documented similarities and differences"))
        return {"focus": focus}, f"Compare documents: {focus}"
    objective = normalize_text(str(raw.get("objective") or "Executive brief"))
    audience = normalize_text(str(raw.get("audience") or "executive"))
    try:
        max_points = int(raw.get("max_points", 5))
    except (TypeError, ValueError) as exc:
        raise ValidationError("max_points must be an integer") from exc
    if max_points < 1 or max_points > 20:
        raise ValidationError("max_points must be between 1 and 20")
    normalized = {"objective": objective, "audience": audience, "max_points": max_points}
    query = f"{objective}. Audience: {audience}. Key facts, risks, and decisions."
    return normalized, query
