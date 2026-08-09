"""Deterministic zero-key providers for local development and tests."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from itertools import pairwise

from agentflow.domain import (
    ProviderResponse,
    ProviderUsage,
    RetrievedChunk,
    WorkflowType,
)
from agentflow.evidence_text import EvidenceExcerpt, select_evidence_excerpt

_TERM_PATTERN = re.compile(r"[\w']+", re.UNICODE)


class DeterministicEmbeddingProvider:
    """Signed feature hashing with no model files or network access."""

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = dimensions

    @property
    def identifier(self) -> str:
        return f"local-feature-hash-v1-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        terms = [term.lower() for term in _TERM_PATTERN.findall(text)]
        features = terms + [f"{left}:{right}" for left, right in pairwise(terms)]
        vector = [0.0] * self._dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            index = raw % self._dimensions
            sign = 1.0 if raw & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class DeterministicResponseProvider:
    """Evidence-only response generation for an honest no-key demo."""

    @property
    def identifier(self) -> str:
        return "local-evidence-template-v2"

    async def generate(
        self,
        *,
        workflow: WorkflowType,
        normalized_input: dict[str, object],
        evidence: list[RetrievedChunk],
    ) -> ProviderResponse:
        candidate_limit = 20 if workflow == WorkflowType.COMPARE else 6
        selected = evidence[: min(candidate_limit, len(evidence))]
        if workflow == WorkflowType.QUESTION:
            structured, text, citation_indices = self._question(normalized_input, selected)
        elif workflow == WorkflowType.COMPARE:
            structured, text, citation_indices = self._compare(normalized_input, selected)
        else:
            structured, text, citation_indices = self._brief(normalized_input, selected)
        input_tokens = sum(len(item.text.split()) for item in selected)
        return ProviderResponse(
            text=text,
            structured=structured,
            citation_indices=citation_indices,
            model_id=self.identifier,
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=len(text.split()),
                generation_calls=1,
            ),
        )

    def _question(
        self,
        normalized_input: dict[str, object],
        evidence: list[RetrievedChunk],
    ) -> tuple[dict[str, object], str, list[int]]:
        question = str(normalized_input.get("question", ""))
        ranked = self._ranked_excerpts(evidence, question)
        relevant = [item for item in ranked if item[2].score > 0]
        selected = (relevant or ranked)[:3]
        statements = [
            f"{excerpt.text} [{citation_number}]"
            for citation_number, (_, _, excerpt) in enumerate(selected, start=1)
        ]
        answer = " ".join(statements)
        citation_indices = [index for index, _, _ in selected]
        return {"question": question, "answer": answer}, answer, citation_indices

    def _compare(
        self,
        normalized_input: dict[str, object],
        evidence: list[RetrievedChunk],
    ) -> tuple[dict[str, object], str, list[int]]:
        focus = str(normalized_input.get("focus", "Key documented differences"))
        by_document: dict[object, list[tuple[int, RetrievedChunk, EvidenceExcerpt]]] = defaultdict(
            list
        )
        for index, item in enumerate(evidence, start=1):
            by_document[item.document_id].append(
                (index - 1, item, select_evidence_excerpt(item.text, focus))
            )
        document_findings: list[dict[str, object]] = []
        rendered: list[str] = []
        citation_indices: list[int] = []
        for items in by_document.values():
            original_index, selected_item, excerpt = max(
                items,
                key=lambda value: (value[2].score, evidence[value[0]].score, -value[0]),
            )
            citation_indices.append(original_index)
            citation_number = len(citation_indices)
            findings = [f"{excerpt.text} [{citation_number}]"]
            document_findings.append(
                {"document": selected_item.document_title, "findings": findings}
            )
            rendered.append(f"{selected_item.document_title}: {' '.join(findings)}")
        text = " ".join(rendered)
        return (
            {
                "focus": focus,
                "summary": text,
                "documents": document_findings,
                "comparison_note": (
                    "The local provider reports documented evidence without inferring "
                    "unsupported similarities."
                ),
            },
            text,
            citation_indices,
        )

    def _brief(
        self,
        normalized_input: dict[str, object],
        evidence: list[RetrievedChunk],
    ) -> tuple[dict[str, object], str, list[int]]:
        objective = str(normalized_input.get("objective", "Executive brief"))
        audience = str(normalized_input.get("audience", "executive"))
        configured_points = normalized_input.get("max_points", 6)
        max_points = max(1, min(configured_points, 6)) if isinstance(configured_points, int) else 6
        ranked = self._ranked_excerpts(evidence, f"{objective} {audience}")
        selected: list[tuple[int, RetrievedChunk, EvidenceExcerpt]] = []
        seen_documents: set[object] = set()
        for item in ranked:
            if item[1].document_id not in seen_documents:
                selected.append(item)
                seen_documents.add(item[1].document_id)
            if len(selected) >= max_points:
                break
        if len(selected) < max_points:
            selected_indices = {item[0] for item in selected}
            selected.extend(item for item in ranked if item[0] not in selected_indices)
            selected = selected[:max_points]
        points = [
            f"{excerpt.text} [{citation_number}]"
            for citation_number, (_, _, excerpt) in enumerate(selected, start=1)
        ]
        citation_indices = [index for index, _, _ in selected]
        text = " ".join(points)
        return (
            {
                "title": objective,
                "audience": audience,
                "executive_summary": text,
                "key_points": points,
            },
            text,
            citation_indices,
        )

    @staticmethod
    def _ranked_excerpts(
        evidence: list[RetrievedChunk],
        query: str,
    ) -> list[tuple[int, RetrievedChunk, EvidenceExcerpt]]:
        ranked = [
            (index, item, select_evidence_excerpt(item.text, query))
            for index, item in enumerate(evidence)
        ]
        ranked.sort(key=lambda value: (-value[2].score, -value[1].score, value[0]))
        return ranked
