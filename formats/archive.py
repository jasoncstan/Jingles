"""ZIP and 7z archive extraction for compressed ROMs.

ZIP is handled via Python's stdlib zipfile module.
7z is handled via the 7z.exe / 7za.exe command-line tool.

extract_rom() extracts ALL archive contents to a temp directory (so that
companion files like .gsflib / .psflib are available alongside the main
ROM), then returns the path to the first supported ROM file found.
The caller is responsible for deleting the temp directory when done.
"""
import os
import zipfile
import tempfile
import subprocess
import shutil

from utils import SUPPORTED_EXTENSIONS

# Formats that require companion files to be present in the same directory
# (e.g. .minigsf needs a .gsflib, .minipsf needs a .psflib, etc.)
_NEEDS_COMPANION = {
    '.minigsf', '.minipsf', '.minipsf2', '.minissf', '.minidsf',
}


def extract_rom(archive_path: str, seven_zip: str = None) -> tuple:
    """Extract contents of a zip or 7z archive to a temp directory.

    Returns (rom_path, temp_dir) where rom_path is the first supported ROM
    found in the extracted directory. Returns (None, None) on failure.
    The caller must delete temp_dir when done.
    """
    ext = os.path.splitext(archive_path)[1].lower()

    if ext == '.zip':
        return _extract_zip(archive_path)
    elif ext == '.7z':
        return _extract_7z(archive_path, seven_zip)

    return None, None


def _find_target(temp_dir: str):
    """Walk temp_dir and return the path to the first supported ROM file.

    Prioritises non-mini files so that a .gsf is preferred over .minigsf
    when both are present (the mini files need the lib from the full file).
    """
    candidates = []
    for root, _, files in os.walk(temp_dir):
        for fname in files:
            fext = os.path.splitext(fname)[1].lower()
            if fext in SUPPORTED_EXTENSIONS and fext not in {'.zip', '.7z'}:
                candidates.append(os.path.join(root, fname))

    if not candidates:
        return None

    # Prefer non-mini formats, then alphabetical
    non_mini = [p for p in candidates
                if os.path.splitext(p)[1].lower() not in _NEEDS_COMPANION]
    return (non_mini or candidates)[0]


def _extract_zip(archive_path: str) -> tuple:
    """Extract all files from a ZIP to a temp directory."""
    try:
        with zipfile.ZipFile(archive_path, 'r') as zf:
            temp_dir = tempfile.mkdtemp(prefix='jingles_zip_')
            zf.extractall(temp_dir)
    except (zipfile.BadZipFile, OSError):
        return None, None

    target = _find_target(temp_dir)
    if target is None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    return target, temp_dir


def _extract_7z(archive_path: str, seven_zip: str) -> tuple:
    """Extract all files from a 7z archive to a temp directory via 7z.exe."""
    if not seven_zip or not os.path.isfile(seven_zip):
        return None, None

    temp_dir = tempfile.mkdtemp(prefix='jingles_7z_')
    try:
        result = subprocess.run(
            [seven_zip, 'x', archive_path, f'-o{temp_dir}', '-y'],
            capture_output=True, timeout=120
        )
    except (subprocess.TimeoutExpired, OSError):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    if result.returncode != 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    target = _find_target(temp_dir)
    if target is None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    return target, temp_dir
