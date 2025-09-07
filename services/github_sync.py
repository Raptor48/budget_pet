import os
import json
import base64
from pathlib import Path
from typing import Optional, Callable
import requests
from .logging_config import get_logger
from .backup import backup_db

class GithubSync:
    """Handles GitHub synchronization for database files."""

    def __init__(self, db_path: Path, owner: str, repo: str, repo_db_path: str, branch: str, token: str, logger):
        self.db_path = db_path
        self.owner = owner
        self.repo = repo
        self.repo_db_path = repo_db_path
        self.branch = branch
        self.token = token
        self.logger = logger
        self._current_sha = None
        self._api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_db_path}"

    @classmethod
    def from_env(cls, db_path: Path, logger):
        """Create GithubSync instance from environment variables."""
        owner = os.getenv("GITHUB_OWNER")
        repo = os.getenv("GITHUB_REPO")
        repo_db_path = os.getenv("GITHUB_DB_PATH", "budget.db")
        branch = os.getenv("GITHUB_BRANCH", "main")
        token = os.getenv("GITHUB_TOKEN")

        if not all([owner, repo, token]):
            logger.warning("GitHub sync disabled: missing GITHUB_OWNER, GITHUB_REPO, or GITHUB_TOKEN")
            return None

        return cls(db_path, owner, repo, repo_db_path, branch, token, logger)

    def _headers(self):
        """Get GitHub API headers."""
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def download_db(self) -> Optional[str]:
        """
        Download database from GitHub to local path.
        Returns SHA of downloaded file, or None if file doesn't exist.
        """
        self.logger.info(f"GitHub: downloading DB from {self._api_url}")

        try:
            response = requests.get(self._api_url, headers=self._headers(),
                                  params={"ref": self.branch})

            if response.status_code == 404:
                self.logger.warning(f"GitHub: DB not found (404) at {self._api_url}")
                return None

            response.raise_for_status()
            data = response.json()

            content = base64.b64decode(data["content"]) if isinstance(data.get("content"), str) else b""
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_bytes(content)

            sha = data.get("sha")
            self._current_sha = sha
            self.logger.info(f"GitHub: downloaded DB, sha={sha}, bytes={len(content)}")
            return sha

        except Exception as e:
            self.logger.error(f"GitHub download failed: {e}")
            raise

    def upload_db(self, prev_sha: Optional[str], message: str) -> Optional[str]:
        """
        Upload database to GitHub.
        Returns new SHA, or raises RuntimeError on 409 conflict.
        """
        self.logger.info(f"GitHub: uploading DB, prev sha={prev_sha}")

        try:
            # Create backup before upload
            backup_db(self.db_path, "push")

            content_b64 = base64.b64encode(self.db_path.read_bytes()).decode()
            payload = {
                "message": message,
                "content": content_b64,
                "branch": self.branch
            }

            if prev_sha:
                payload["sha"] = prev_sha

            response = requests.put(self._api_url, headers=self._headers(),
                                  data=json.dumps(payload))

            if response.status_code == 409:
                raise RuntimeError("409")  # Conflict - remote has changed

            response.raise_for_status()
            new_sha = response.json()["content"]["sha"]
            self._current_sha = new_sha
            self.logger.info(f"GitHub: uploaded DB, new sha={new_sha}")
            return new_sha

        except Exception as e:
            self.logger.error(f"GitHub upload failed: {e}")
            raise

    def push_best_effort(self, message: str, on_merge: Optional[Callable] = None) -> None:
        """
        Push database with conflict resolution.
        Attempts soft-merge on 409, then retries push.
        """
        prev_sha = self._current_sha

        try:
            new_sha = self.upload_db(prev_sha, message)
            if new_sha:
                self._current_sha = new_sha
        except RuntimeError as e:
            if "409" in str(e):
                self.logger.warning("Push conflict (409). Pulling latest and retrying...")
                try:
                    # Pull latest
                    pulled_sha = self.download_db()
                    if pulled_sha:
                        self._current_sha = pulled_sha

                        # Attempt merge if callback provided
                        if on_merge:
                            on_merge()

                        # Retry push
                        new_sha = self.upload_db(self._current_sha, message + " (retry)")
                        if new_sha:
                            self._current_sha = new_sha
                            self.logger.info(f"Retry push ok, sha={new_sha}")
                except Exception as retry_error:
                    self.logger.error(f"Retry push failed: {retry_error}")
                    raise
            else:
                raise

    def periodic_pull(self, on_pulled: Callable[[Optional[str]], None]) -> None:
        """
        Perform periodic pull and call callback if SHA changed.
        """
        try:
            new_sha = self.download_db()
            if new_sha and new_sha != self._current_sha:
                self._current_sha = new_sha
                self.logger.info(f"Periodic pull: new sha={new_sha} — calling callback")
                on_pulled(new_sha)
        except Exception as e:
            self.logger.warning(f"Periodic pull failed: {e}")

    def get_current_sha(self) -> Optional[str]:
        """Get current SHA."""
        return self._current_sha

    def set_current_sha(self, sha: Optional[str]) -> None:
        """Set current SHA."""
        self._current_sha = sha
