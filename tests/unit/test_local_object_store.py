from __future__ import annotations

import hashlib

import pytest

from agentflow.errors import NotFoundError, UnsafeDocumentError
from agentflow.object_store.local import LocalObjectStore, validate_object_key


@pytest.mark.parametrize(
    "key",
    ["", "/absolute.txt", "../escape.txt", "safe/../../escape.txt", "bad\\path.txt"],
)
def test_object_key_rejects_unsafe_paths(key: str) -> None:
    with pytest.raises(UnsafeDocumentError):
        validate_object_key(key)


async def test_local_object_store_round_trip_is_checksum_guarded(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"synthetic document bytes"
    checksum = hashlib.sha256(payload).hexdigest()

    metadata = await store.put(
        "workspace/document/version.md",
        payload,
        content_type="text/markdown",
        checksum_sha256=checksum,
    )

    assert metadata.etag == checksum
    assert await store.get(metadata.key) == payload
    assert (await store.head(metadata.key)).size_bytes == len(payload)

    await store.delete(metadata.key)
    with pytest.raises(NotFoundError):
        await store.get(metadata.key)


async def test_local_object_store_rejects_wrong_checksum(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    with pytest.raises(UnsafeDocumentError, match="checksum"):
        await store.put(
            "workspace/document/version.md",
            b"content",
            content_type="text/markdown",
            checksum_sha256="0" * 64,
        )
