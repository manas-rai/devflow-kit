"""Object-storage backend for Graphify code graphs.

Persists each target repo's Graphify artifacts — ``GRAPH_REPORT.md`` plus the
``graphify-out/`` per-file cache — to an S3-compatible bucket, so agents can read
a repo's knowledge graph on demand and incremental updates can restore the cache.

Endpoint-configurable: works with AWS S3, GCS (S3 interop), Cloudflare R2, or
MinIO via ``GRAPH_STORE_ENDPOINT``. Credentials come from the standard AWS
environment variables that boto3 reads automatically.

There is no shared global manifest: each repo's ``manifest.json`` holds its own
``last_sha``, so concurrent updates to different repos cannot clobber each other.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def repo_key(repo: str) -> str:
    """Convert ``owner/name`` into a key-safe ``owner__name``."""
    return repo.replace("/", "__")


@dataclass
class RepoGraphMeta:
    """Metadata stored alongside a repo's graph artifacts."""

    repo: str
    last_sha: str
    updated_at: str
    graphify_version: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "repo": self.repo,
            "last_sha": self.last_sha,
            "updated_at": self.updated_at,
            "graphify_version": self.graphify_version,
            "model": self.model,
        }


class GraphStore:
    """Read/write Graphify artifacts in an S3-compatible bucket.

    Pass ``client`` to inject a stub in tests; otherwise a boto3 S3 client is
    built lazily from the environment.
    """

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        client: Any = None,
    ) -> None:
        self.bucket = bucket or os.environ.get("GRAPH_STORE_BUCKET", "")
        if not self.bucket:
            raise ValueError("GRAPH_STORE_BUCKET is not set")
        self.prefix = (prefix or os.environ.get("GRAPH_STORE_PREFIX", "graphs")).strip("/")
        self._client = client if client is not None else self._default_client()

    @staticmethod
    def _default_client() -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "The 'boto3' package is required for GraphStore. "
                "Install it with: pip install 'devflow-kit[storage]' or pip install boto3"
            ) from exc
        endpoint = os.environ.get("GRAPH_STORE_ENDPOINT") or None
        region = os.environ.get("AWS_REGION") or None
        return boto3.client("s3", endpoint_url=endpoint, region_name=region)

    # --- key helpers -------------------------------------------------------

    def _repo_prefix(self, repo: str) -> str:
        return f"{self.prefix}/{repo_key(repo)}"

    def _report_key(self, repo: str) -> str:
        return f"{self._repo_prefix(repo)}/GRAPH_REPORT.md"

    def _manifest_key(self, repo: str) -> str:
        return f"{self._repo_prefix(repo)}/manifest.json"

    def _cache_prefix(self, repo: str) -> str:
        return f"{self._repo_prefix(repo)}/cache"

    # --- object helpers ----------------------------------------------------

    def _get_text(self, key: str) -> str | None:
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception:
            return None
        return resp["Body"].read().decode("utf-8")

    def _put_text(self, key: str, body: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=body.encode("utf-8"))

    # --- public API --------------------------------------------------------

    def get_repo_meta(self, repo: str) -> RepoGraphMeta | None:
        """Return the stored metadata for a repo, or None if it has no graph yet."""
        raw = self._get_text(self._manifest_key(repo))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return RepoGraphMeta(
            repo=data.get("repo", repo),
            last_sha=data.get("last_sha", ""),
            updated_at=data.get("updated_at", ""),
            graphify_version=data.get("graphify_version", ""),
            model=data.get("model", ""),
        )

    def head_sha(self, repo: str) -> str | None:
        """Return the commit SHA the stored graph was built from, or None."""
        meta = self.get_repo_meta(repo)
        return meta.last_sha if meta else None

    def read_report(self, repo: str) -> str | None:
        """Return the stored ``GRAPH_REPORT.md`` text, or None if absent."""
        return self._get_text(self._report_key(repo))

    def download_cache(self, repo: str, dest_dir: Path) -> bool:
        """Download the stored ``graphify-out/`` cache into ``dest_dir``.

        Returns True if at least one object was copied (i.e. a cache exists).
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        cache_prefix = self._cache_prefix(repo) + "/"
        paginator = self._client.get_paginator("list_objects_v2")
        found = False
        for page in paginator.paginate(Bucket=self.bucket, Prefix=cache_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                rel = key[len(cache_prefix) :]
                if not rel:
                    continue
                target = dest_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                self._client.download_file(self.bucket, key, str(target))
                found = True
        return found

    def upload_graph(
        self,
        repo: str,
        report_path: Path,
        cache_dir: Path,
        sha: str,
        *,
        updated_at: str,
        graphify_version: str = "",
        model: str = "",
    ) -> RepoGraphMeta:
        """Upload a repo's report, cache, and manifest. Returns the new metadata."""
        report_text = Path(report_path).read_text(encoding="utf-8", errors="replace")
        self._put_text(self._report_key(repo), report_text)

        cache_dir = Path(cache_dir)
        if cache_dir.exists():
            cache_prefix = self._cache_prefix(repo)
            for f in cache_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(cache_dir).as_posix()
                    self._client.upload_file(str(f), self.bucket, f"{cache_prefix}/{rel}")

        meta = RepoGraphMeta(repo, sha, updated_at, graphify_version, model)
        self._put_text(self._manifest_key(repo), json.dumps(meta.to_dict(), indent=2))
        return meta
