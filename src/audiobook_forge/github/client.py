"""Thin, resilient GitHub REST API client.

Only the endpoints the system actually needs are implemented:

* Releases as transient object storage for *intake* uploads (bot -> runner).
* Releases as the durable delivery channel for finished audiobooks.
* ``workflow_dispatch`` to hand a task off to a free GitHub-hosted runner.

The access token is **never** stored in code or config. It is read from the
environment (``GITHUB_TOKEN`` / ``GH_TOKEN``), which in GitHub Actions is the
auto-provisioned secret and locally comes from the operator's ``.env`` or shell.

All network calls go through :func:`tenacity` retries so transient 5xx / network
blips do not fail a whole conversion.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..core.errors import GitHubError
from ..utils.logging import get_logger

logger = get_logger(__name__)

_TOKEN_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")
_UPLOADS_BASE = "https://uploads.github.com"
_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


def _resolve_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    for key in _TOKEN_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return value
    return ""


class GitHubClient:
    """Minimal GitHub REST client scoped to a single ``owner/repo``."""

    def __init__(
        self,
        repository: str,
        token: str | None = None,
        api_url: str = "https://api.github.com",
        uploads_url: str = _UPLOADS_BASE,
        timeout: float = 60.0,
    ) -> None:
        if not repository:
            raise GitHubError("GITHUB_REPOSITORY is not configured (expected 'owner/name').")
        self._repo = repository
        self._api = api_url.rstrip("/")
        self._uploads = uploads_url.rstrip("/")
        self._token = _resolve_token(token)
        if not self._token:
            logger.warning("No GitHub token found in environment; API calls will likely fail.")
        self._timeout = timeout

    # -- low-level helpers -------------------------------------------------

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> httpx.Response:
        full = url if url.startswith("http") else f"{self._api}{url}"
        response = httpx.request(
            method,
            full,
            headers=headers or self._headers(),
            json=json,
            content=content,
            timeout=self._timeout,
            follow_redirects=True,
        )
        if response.status_code not in expected:
            # Raise for status so retryable 5xx are retried; wrap others.
            if response.status_code >= 500:
                response.raise_for_status()
            raise GitHubError(
                f"{method} {full} -> {response.status_code}: {response.text[:400]}"
            )
        return response

    # -- releases ----------------------------------------------------------

    def get_release_by_tag(self, tag: str) -> dict[str, Any] | None:
        """Return the release for ``tag`` or ``None`` if it does not exist."""
        url = f"/repos/{self._repo}/releases/tags/{tag}"
        try:
            response = self._request("GET", url, expected=(200,))
        except GitHubError:
            return None
        return response.json()

    def ensure_release(
        self,
        tag: str,
        name: str,
        body: str = "",
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        """Return an existing release for ``tag`` or create a new one."""
        existing = self.get_release_by_tag(tag)
        if existing:
            return existing
        payload = {
            "tag_name": tag,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        response = self._request(
            "POST", f"/repos/{self._repo}/releases", json=payload, expected=(201,)
        )
        logger.info("Created release %s", tag)
        return response.json()

    def upload_asset(self, release: dict[str, Any], path: Path) -> dict[str, Any]:
        """Upload ``path`` as an asset of ``release`` (replacing a stale copy)."""
        release_id = release["id"]
        name = path.name
        # Remove any pre-existing asset with the same name (idempotent resume).
        for asset in release.get("assets", []):
            if asset.get("name") == name:
                self._request(
                    "DELETE",
                    f"/repos/{self._repo}/releases/assets/{asset['id']}",
                    expected=(204,),
                )
        upload_url = f"{self._uploads}/repos/{self._repo}/releases/{release_id}/assets"
        headers = self._headers(accept="application/vnd.github+json")
        headers["Content-Type"] = "application/octet-stream"
        response = self._request(
            "POST",
            f"{upload_url}?name={name}",
            headers=headers,
            content=path.read_bytes(),
            expected=(201,),
        )
        return response.json()

    def download_asset(self, asset_api_url: str, dst: Path) -> Path:
        """Download a release asset (by its API ``url``) to ``dst``."""
        headers = self._headers(accept="application/octet-stream")
        response = self._request("GET", asset_api_url, headers=headers, expected=(200,))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(response.content)
        return dst

    def delete_release(self, tag: str) -> None:
        """Delete the release for ``tag`` and its git tag ref (best effort)."""
        release = self.get_release_by_tag(tag)
        if not release:
            return
        self._request(
            "DELETE",
            f"/repos/{self._repo}/releases/{release['id']}",
            expected=(204,),
        )
        try:
            self._request(
                "DELETE",
                f"/repos/{self._repo}/git/refs/tags/{tag}",
                expected=(204,),
            )
        except GitHubError:
            logger.debug("Tag ref %s already gone", tag)

    # -- actions -----------------------------------------------------------

    def dispatch_workflow(
        self, workflow_file: str, ref: str, inputs: dict[str, str]
    ) -> None:
        """Trigger a ``workflow_dispatch`` event for ``workflow_file``."""
        url = f"/repos/{self._repo}/actions/workflows/{workflow_file}/dispatches"
        self._request("POST", url, json={"ref": ref, "inputs": inputs}, expected=(204,))
        logger.info("Dispatched workflow %s on %s", workflow_file, ref)
