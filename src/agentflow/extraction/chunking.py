"""Deterministic, overlapping text chunking that preserves source locators."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentflow.extraction.documents import ExtractedDocument

_TOKEN_PATTERN = re.compile(r"\S+")


class ChunkDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int = Field(ge=0)
    text: str
    token_count: int = Field(ge=1)
    locator: dict[str, Any] = Field(default_factory=dict)


class TextChunker:
    def __init__(self, *, chunk_size_tokens: int, overlap_tokens: int) -> None:
        if overlap_tokens >= chunk_size_tokens:
            raise ValueError("chunk overlap must be smaller than chunk size")
        self._chunk_size = chunk_size_tokens
        self._overlap = overlap_tokens

    def chunk(self, document: ExtractedDocument) -> list[ChunkDraft]:
        located_tokens: list[tuple[str, dict[str, Any]]] = []
        for block in document.blocks:
            located_tokens.extend(
                (match.group(0), block.locator) for match in _TOKEN_PATTERN.finditer(block.text)
            )
        if not located_tokens:
            return []

        chunks: list[ChunkDraft] = []
        step = self._chunk_size - self._overlap
        for start in range(0, len(located_tokens), step):
            selected = located_tokens[start : start + self._chunk_size]
            if not selected:
                break
            text = " ".join(token for token, _ in selected)
            first_locator = selected[0][1]
            last_locator = selected[-1][1]
            locator: dict[str, Any] = {
                "token_start": start,
                "token_end": start + len(selected),
            }
            if first_locator == last_locator:
                locator.update(first_locator)
            else:
                locator["start"] = first_locator
                locator["end"] = last_locator
            chunks.append(
                ChunkDraft(
                    ordinal=len(chunks),
                    text=text,
                    token_count=len(selected),
                    locator=locator,
                )
            )
            if start + self._chunk_size >= len(located_tokens):
                break
        return chunks
