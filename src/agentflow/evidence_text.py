"""Deterministic extraction of relevant, exact spans from untrusted evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TERM_PATTERN = re.compile(r"[\w']+", re.UNICODE)
_SENTENCE_PATTERN = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}
_METADATA_MARKERS = (
    "document id:",
    "effective date:",
    "revision:",
    "owner:",
    "this document is synthetic",
)
_INSTRUCTION_MARKERS = (
    "ignore previous",
    "ignore the workflow",
    "return every secret",
    "reveal the system prompt",
    "follow these instructions",
)
_POLICY_MARKERS = (
    "must",
    "requires",
    "commits",
    "within",
    "retained",
    "encrypt",
    "availability",
    "response",
    "days",
    "hours",
    "tls",
    "aes",
)


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    """A source-exact excerpt and its deterministic relevance score."""

    text: str
    score: float


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    text: str


def _stem(term: str) -> str:
    value = term.casefold().strip("'")
    for suffix in ("ations", "ation", "ions", "ion", "ing", "ied", "ed", "es", "s"):
        if value.endswith(suffix) and len(value) - len(suffix) >= 4:
            if suffix == "ied":
                return value[: -len(suffix)] + "y"
            return value[: -len(suffix)]
    return value


def _terms(value: str) -> set[str]:
    return {
        stemmed
        for raw in _TERM_PATTERN.findall(value)
        if (stemmed := _stem(raw)) and stemmed not in _STOP_WORDS
    }


def _spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for match in _SENTENCE_PATTERN.finditer(text):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append(_Span(start=start, end=end, text=text[start:end]))
    return spans


def _relevance(span: _Span, query_terms: set[str]) -> float:
    span_terms = _terms(span.text)
    overlap = len(query_terms & span_terms)
    score = float(overlap * 4)
    normalized = span.text.casefold()
    score += sum(0.25 for marker in _POLICY_MARKERS if marker in normalized)
    if any(marker in normalized for marker in _METADATA_MARKERS):
        score -= 2
    if any(marker in normalized for marker in _INSTRUCTION_MARKERS) and overlap == 0:
        score -= 20
    return score


def _fallback_score(span: _Span) -> float:
    normalized = span.text.casefold()
    words = len(_TERM_PATTERN.findall(span.text))
    score = min(words, 40) / 40
    score += sum(0.25 for marker in _POLICY_MARKERS if marker in normalized)
    if any(marker in normalized for marker in _METADATA_MARKERS):
        score -= 2
    if any(marker in normalized for marker in _INSTRUCTION_MARKERS):
        score -= 20
    return score


def select_evidence_excerpt(
    text: str,
    query: str,
    *,
    max_chars: int = 360,
    max_sentences: int = 2,
) -> EvidenceExcerpt:
    """Select a relevant contiguous span without altering source characters."""

    if max_chars < 1 or max_sentences < 1:
        raise ValueError("excerpt bounds must be positive")
    spans = _spans(text)
    if not spans:
        exact = text.strip()[:max_chars]
        return EvidenceExcerpt(text=exact, score=0)

    query_terms = _terms(query)
    scored = [_relevance(span, query_terms) for span in spans]
    if max(scored, default=0) > 0:
        best_index = max(range(len(spans)), key=lambda index: (scored[index], -index))
        best_score = scored[best_index]
    else:
        best_index = max(
            range(len(spans)),
            key=lambda index: (_fallback_score(spans[index]), -index),
        )
        best_score = 0.0

    selected = {best_index}
    adjacent = [index for index in (best_index - 1, best_index + 1) if 0 <= index < len(spans)]
    adjacent.sort(key=lambda index: (-scored[index], abs(index - best_index), index))
    for index in adjacent:
        if len(selected) >= max_sentences or scored[index] <= 0:
            continue
        proposed = selected | {index}
        start = spans[min(proposed)].start
        end = spans[max(proposed)].end
        if end - start <= max_chars:
            selected = proposed

    start = spans[min(selected)].start
    end = spans[max(selected)].end
    if end - start > max_chars:
        span = spans[best_index]
        start = span.start
        end = min(span.end, span.start + max_chars)
    return EvidenceExcerpt(text=text[start:end].strip(), score=best_score)
