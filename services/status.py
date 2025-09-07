from datetime import datetime

class StatusManager:
    """Manages application status messages and error counters."""

    def __init__(self):
        self.last_sync = None
        self.error_count = 0

    def set_status(self, text: str) -> None:
        """Set the last sync status text."""
        self.last_sync = text

    def inc_error(self, what: str = "") -> None:
        """Increment error counter."""
        self.error_count += 1

    def get_status_text(self) -> str:
        """Get formatted status text for display."""
        last_sync_text = self.last_sync or "-"
        return f"Last sync: {last_sync_text}  |  Errors: {self.error_count}"
