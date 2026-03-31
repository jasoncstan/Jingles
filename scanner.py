"""ROM file scanner: find all supported ROMs in a directory tree."""
import os
from pathlib import Path
from utils import SUPPORTED_EXTENSIONS


def _is_wiiu_game_folder(path: Path) -> bool:
    """Check if a directory is a decrypted Wii U game (code/content/meta)."""
    if not path.is_dir():
        return False
    meta = path / 'meta'
    if not meta.is_dir():
        return False
    # Must have bootSound.btsnd (case-insensitive check)
    for f in meta.iterdir():
        if f.name.lower() == 'bootsound.btsnd' and f.is_file():
            return True
    return False


def scan_directory(directory: str, recursive: bool = True) -> list:
    """Return a sorted list of Path objects for all ROM files under directory.

    Also detects decrypted Wii U game folders (containing meta/bootSound.btsnd)
    and returns the bootSound.btsnd file as the "ROM" path.

    Args:
        directory: Root directory to search.
        recursive: If True (default), walk all subdirectories.

    Returns:
        List of pathlib.Path objects sorted by full path string.
    """
    root = Path(directory)
    results = []
    wiiu_dirs = set()  # track Wii U game dirs to avoid duplicates

    if recursive:
        for path in root.rglob('*'):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                # Skip .btsnd files here — they're picked up by the
                # Wii U folder scan below to avoid duplicates.
                if path.suffix.lower() == '.btsnd':
                    continue
                results.append(path)
        # Scan for Wii U game folders
        for path in root.rglob('meta'):
            if path.is_dir():
                game_dir = path.parent
                if game_dir not in wiiu_dirs and _is_wiiu_game_folder(game_dir):
                    wiiu_dirs.add(game_dir)
                    for f in path.iterdir():
                        if f.name.lower() == 'bootsound.btsnd':
                            results.append(f)
                            break
    else:
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                if path.suffix.lower() == '.btsnd':
                    continue
                results.append(path)
            elif _is_wiiu_game_folder(path):
                meta = path / 'meta'
                for f in meta.iterdir():
                    if f.name.lower() == 'bootsound.btsnd':
                        results.append(f)
                        break

    return sorted(results, key=lambda p: str(p).lower())
