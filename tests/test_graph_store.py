"""Tests for the Graphify object-storage backend, using an in-memory S3 stub."""

import io
from pathlib import Path

from tools.graph_store import GraphStore, repo_key


class _FakePaginator:
    def __init__(self, store: dict[str, bytes]):
        self._store = store

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 kwarg names
        contents = [{"Key": k} for k in self._store if k.startswith(Prefix)]
        yield {"Contents": contents}


class FakeS3:
    """Minimal in-memory stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.store[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.store:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.store[Key])}

    def get_paginator(self, name):
        return _FakePaginator(self.store)

    def upload_file(self, filename, Bucket, Key):  # noqa: N803
        self.store[Key] = Path(filename).read_bytes()

    def download_file(self, Bucket, Key, filename):  # noqa: N803
        Path(filename).write_bytes(self.store[Key])


def _store() -> tuple[GraphStore, FakeS3]:
    fake = FakeS3()
    return GraphStore(bucket="test-bucket", client=fake), fake


def test_repo_key_sanitizes_slash():
    assert repo_key("manas-rai/cloud-waste-hunter") == "manas-rai__cloud-waste-hunter"


def test_head_sha_none_when_unbuilt():
    store, _ = _store()
    assert store.head_sha("org/repo") is None
    assert store.read_report("org/repo") is None


def test_upload_then_read_report_and_sha(tmp_path):
    store, _ = _store()
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("# Graph\nCommunity Hubs: auth, billing\n")
    cache = tmp_path / "graphify-out"
    cache.mkdir()

    meta = store.upload_graph(
        "org/repo", report, cache, "abc123", updated_at="2026-06-24T00:00:00Z"
    )

    assert meta.last_sha == "abc123"
    assert store.head_sha("org/repo") == "abc123"
    assert "Community Hubs" in store.read_report("org/repo")


def test_cache_roundtrip(tmp_path):
    store, _ = _store()
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("report")
    cache = tmp_path / "graphify-out"
    (cache / "nested").mkdir(parents=True)
    (cache / "a.json").write_text("aaa")
    (cache / "nested" / "b.json").write_text("bbb")

    store.upload_graph("org/repo", report, cache, "sha", updated_at="now")

    dest = tmp_path / "restored"
    assert store.download_cache("org/repo", dest) is True
    assert (dest / "a.json").read_text() == "aaa"
    assert (dest / "nested" / "b.json").read_text() == "bbb"


def test_download_cache_false_when_empty(tmp_path):
    store, _ = _store()
    assert store.download_cache("org/repo", tmp_path / "dest") is False
