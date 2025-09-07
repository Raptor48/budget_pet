import shutil
from pathlib import Path
from datetime import datetime

def backup_db(db_file: str | Path, reason: str = "manual") -> None:
    """Create a backup of the database file and rotate to keep last 7 backups."""
    try:
        db_path = Path(db_file)
        backup_dir = db_path.with_name("backups")
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_file = backup_dir / f"budget_{timestamp}_{reason}.db"

        shutil.copy2(db_path, backup_file)

        # Rotate to keep last 7 backups
        backups = sorted(backup_dir.glob("budget_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_backup in backups[7:]:
            try:
                old_backup.unlink()
            except Exception:
                pass
    except Exception:
        # Silently fail for backup creation
        pass
