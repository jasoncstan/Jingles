"""ROM file scanner: find all supported ROMs in a directory tree."""
import os
from pathlib import Path
from utils import SUPPORTED_EXTENSIONS


def scan_directory(directory: str, recursive: bool = True) -> list:
    """Return a sorted list of Path objects for all ROM files under directory.

    Args:
        directory: Root directory to search.
        recursive: If True (default), walk all subdirectories.

    Returns:
        List of pathlib.Path objects sorted by full path string.
    """
    root = Path(directory)
    results = []

    if recursive:
        for path in root.rglob('*'):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                results.append(path)
    else:
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                results.append(path)

    return sorted(results, key=lambda p: str(p).lower())
