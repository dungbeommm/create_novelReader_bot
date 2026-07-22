"""GitHub Release publisher implementing the ReleasePublisher port."""

from __future__ import annotations

from pathlib import Path

from ..config.models import ReleaseSettings
from ..utils.logging import get_logger
from .client import GitHubClient

logger = get_logger(__name__)


class GitHubReleasePublisher:
    """Creates a release and uploads assets, returning the release URL."""

    def __init__(self, client: GitHubClient, settings: ReleaseSettings) -> None:
        self._client = client
        self._settings = settings

    def publish(self, tag: str, name: str, files: list[Path], body: str) -> str:
        """Publish ``files`` under a release tagged ``tag``.

        Args:
            tag: Git tag for the release (created if missing).
            name: Human-readable release name.
            files: Assets to upload (audio, metadata, playlist, cover, log).
            body: Markdown release notes.

        Returns:
            The release HTML URL.
        """
        release = self._client.ensure_release(
            tag=tag,
            name=name,
            body=body,
            draft=self._settings.draft,
            prerelease=self._settings.prerelease,
        )
        for file in files:
            if not file.exists():
                logger.warning("Skipping missing asset: %s", file)
                continue
            logger.info("Uploading asset %s", file.name)
            self._client.upload_asset(release, file)
        return str(release.get("html_url", ""))
