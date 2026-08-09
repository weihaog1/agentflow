"""Safe, bounded extraction for the supported document formats."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

from defusedxml import ElementTree
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from agentflow.errors import UnsafeDocumentError, UnsupportedDocumentError

_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_ALLOWED_MEDIA_TYPES: dict[str, set[str]] = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}


class ExtractedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    locator: dict[str, Any] = Field(default_factory=dict)


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    media_type: str
    blocks: list[ExtractedBlock]
    character_count: int = Field(ge=0)


class DocumentExtractor:
    def __init__(
        self,
        *,
        allowed_extensions: tuple[str, ...],
        max_upload_bytes: int,
        max_extracted_chars: int,
        max_pdf_pages: int,
        max_docx_entries: int,
        max_docx_uncompressed_bytes: int,
    ) -> None:
        self._allowed_extensions = set(allowed_extensions)
        self._max_upload_bytes = max_upload_bytes
        self._max_extracted_chars = max_extracted_chars
        self._max_pdf_pages = max_pdf_pages
        self._max_docx_entries = max_docx_entries
        self._max_docx_uncompressed_bytes = max_docx_uncompressed_bytes

    def normalize_filename(self, filename: str) -> str:
        normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
        basename = normalized.rsplit("/", maxsplit=1)[-1]
        basename = "".join(
            char for char in basename if char.isprintable() and char != "\x00"
        ).strip()
        basename = re.sub(r"\s+", " ", basename)
        if not basename or basename in {".", ".."}:
            raise UnsafeDocumentError("document filename is empty or unsafe")
        return basename[:240]

    def validate(self, *, filename: str, media_type: str, data: bytes) -> tuple[str, str]:
        safe_filename = self.normalize_filename(filename)
        extension = Path(safe_filename).suffix.lower()
        normalized_media_type = media_type.split(";", maxsplit=1)[0].strip().lower()
        if extension not in self._allowed_extensions or extension not in _ALLOWED_MEDIA_TYPES:
            raise UnsupportedDocumentError(
                "document extension is not supported",
                details={"extension": extension},
            )
        if normalized_media_type not in _ALLOWED_MEDIA_TYPES[extension]:
            raise UnsupportedDocumentError(
                "document media type does not match its extension",
                details={"extension": extension, "media_type": normalized_media_type},
            )
        if not data:
            raise UnsafeDocumentError("document is empty")
        if len(data) > self._max_upload_bytes:
            raise UnsafeDocumentError(
                "document exceeds the upload limit",
                details={"max_bytes": self._max_upload_bytes},
            )
        if extension == ".pdf" and not data.startswith(b"%PDF-"):
            raise UnsafeDocumentError("PDF signature is invalid")
        if extension == ".docx" and not data.startswith(b"PK"):
            raise UnsafeDocumentError("DOCX container signature is invalid")
        if extension in {".txt", ".md"} and b"\x00" in data[:8192]:
            raise UnsafeDocumentError("text document contains binary data")
        return safe_filename, normalized_media_type

    def extract(self, *, filename: str, media_type: str, data: bytes) -> ExtractedDocument:
        safe_filename, normalized_media_type = self.validate(
            filename=filename,
            media_type=media_type,
            data=data,
        )
        extension = Path(safe_filename).suffix.lower()
        if extension in {".txt", ".md"}:
            blocks = self._extract_text(data)
        elif extension == ".pdf":
            blocks = self._extract_pdf(data)
        elif extension == ".docx":
            blocks = self._extract_docx(data)
        else:
            raise UnsupportedDocumentError("document extension is not supported")
        blocks = [block for block in blocks if block.text.strip()]
        character_count = sum(len(block.text) for block in blocks)
        if not blocks:
            raise UnsafeDocumentError("document did not contain extractable text")
        if character_count > self._max_extracted_chars:
            raise UnsafeDocumentError(
                "extracted text exceeds the configured limit",
                details={"max_characters": self._max_extracted_chars},
            )
        return ExtractedDocument(
            filename=safe_filename,
            media_type=normalized_media_type,
            blocks=blocks,
            character_count=character_count,
        )

    def _extract_text(self, data: bytes) -> list[ExtractedBlock]:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("utf-16")
            except UnicodeDecodeError as exc:
                raise UnsafeDocumentError("text document is not valid UTF-8 or UTF-16") from exc
        paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
        return [
            ExtractedBlock(text=paragraph.strip(), locator={"paragraph": index + 1})
            for index, paragraph in enumerate(paragraphs)
            if paragraph.strip()
        ]

    def _extract_pdf(self, data: bytes) -> list[ExtractedBlock]:
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise UnsafeDocumentError("encrypted PDFs are not supported")
            if len(reader.pages) > self._max_pdf_pages:
                raise UnsafeDocumentError(
                    "PDF exceeds the page limit",
                    details={"max_pages": self._max_pdf_pages},
                )
            blocks: list[ExtractedBlock] = []
            extracted_count = 0
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                extracted_count += len(text)
                if extracted_count > self._max_extracted_chars:
                    raise UnsafeDocumentError("PDF extracted text exceeds the configured limit")
                if text:
                    blocks.append(ExtractedBlock(text=text, locator={"page": page_number}))
            return blocks
        except UnsafeDocumentError:
            raise
        except Exception as exc:
            raise UnsafeDocumentError("PDF could not be parsed safely") from exc

    def _extract_docx(self, data: bytes) -> list[ExtractedBlock]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > self._max_docx_entries:
                    raise UnsafeDocumentError("DOCX contains too many archive entries")
                total_uncompressed = 0
                for entry in entries:
                    entry_path = Path(entry.filename)
                    if entry_path.is_absolute() or ".." in entry_path.parts:
                        raise UnsafeDocumentError("DOCX contains an unsafe archive path")
                    total_uncompressed += entry.file_size
                    if total_uncompressed > self._max_docx_uncompressed_bytes:
                        raise UnsafeDocumentError("DOCX expands beyond the configured limit")
                    if entry.compress_size and entry.file_size / entry.compress_size > 200:
                        raise UnsafeDocumentError("DOCX contains a suspicious compression ratio")
                if "word/vbaProject.bin" in archive.namelist():
                    raise UnsafeDocumentError("macro-enabled documents are not supported")
                try:
                    document_xml = archive.read("word/document.xml")
                except KeyError as exc:
                    raise UnsafeDocumentError("DOCX is missing its document body") from exc
        except UnsafeDocumentError:
            raise
        except (zipfile.BadZipFile, OSError) as exc:
            raise UnsafeDocumentError("DOCX container is invalid") from exc

        try:
            root = ElementTree.fromstring(document_xml)
        except ElementTree.ParseError as exc:
            raise UnsafeDocumentError("DOCX XML is invalid") from exc
        blocks: list[ExtractedBlock] = []
        paragraph_number = 0
        for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
            text_parts = [node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")]
            text = "".join(text_parts).strip()
            if text:
                paragraph_number += 1
                blocks.append(ExtractedBlock(text=text, locator={"paragraph": paragraph_number}))
        return blocks
