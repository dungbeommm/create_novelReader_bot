"""Bridge between the Telegram bot and GitHub Actions.

The bot never runs heavy TTS itself. Instead it:
1. Uploads the user's ebook(s) to a transient "intake" GitHub Release used as
   temporary object storage (works well within GitHub Free limits).
2. Fires a ``workflow_dispatch`` event carrying the task metadata + option
   choices + chat id, so the runner can process the job and notify the user.

This keeps the always-on component tiny (cheap to host) while the CPU-heavy
work runs on free GitHub runners.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config.models import Settings
from ..core.domain import Task
from ..github.client import GitHubClient
from ..utils.logging import get_logger

logger = get_logger(__name__)


class ActionsDispatcher:
    """Uploads intake files and triggers the conversion workflow."""

    def __init__(self, settings: Settings, client: GitHubClient) -> None:
        self._settings = settings
        self._client = client

    def _intake_tag(self, task: Task) -> str:
        return f"{self._settings.github.intake_tag_prefix}-{task.id}"

    def upload_intake(self, task: Task) -> str:
        """Upload source files to a transient release and return its tag.

        The release is created as a prerelease so it stays out of the main
        release list; the worker deletes it during cleanup.
        """
        tag = self._intake_tag(task)
        release = self._client.ensure_release(
            tag=tag,
            name=f"Intake {task.id}",
            body="Transient upload for Audiobook Forge. Safe to delete.",
            prerelease=True,
        )
        for file in task.source_files:
            path = Path(file)
            if path.exists():
                logger.info("Uploading intake asset %s", path.name)
                self._client.upload_asset(release, path)
        return tag

    def dispatch(self, task: Task) -> None:
        """Upload intake files then trigger the conversion workflow."""
        tag = self.upload_intake(task)
        task.intake_ref = tag
        inputs = {
            "task_id": task.id,
            "chat_id": str(task.chat_id),
            "user_id": str(task.user_id),
            "intake_tag": tag,
            "options": json.dumps(task.options.to_dict(), ensure_ascii=False),
            "source_names": json.dumps([Path(f).name for f in task.source_files]),
        }
        self._client.dispatch_workflow(
            workflow_file=self._settings.github.workflow_file,
            ref=self._settings.github.ref,
            inputs=inputs,
        )
        logger.info("Dispatched conversion workflow for task %s", task.id)
