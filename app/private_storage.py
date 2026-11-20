"""Desktop storage for files kept under the current user's application data."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths


def private_folder() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not location:
        raise OSError("The application data folder is unavailable.")
    folder = Path(location) / "private-images"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder
