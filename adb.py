"""ADB (Android Debug Bridge) integration for Jingles.

Provides device discovery, remote file scanning, pull/push operations,
and a local ROM cache to avoid redundant transfers.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath

from utils import SUPPORTED_EXTENSIONS

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ADB_CACHE_DIR = os.path.join(APP_DIR, 'adb_cache')
_MANIFEST_FILE = os.path.join(ADB_CACHE_DIR, '_manifest.json')

# Timeout for ADB commands (seconds)
_CMD_TIMEOUT = 30
_PULL_TIMEOUT = 600   # 10 min for large ROMs
_PUSH_TIMEOUT = 600


# ── ADB detection ────────────────────────────────────────────────────────────

def find_adb() -> str | None:
    """Return the path to the adb executable, or None if not found.

    Search order:
      1. tools/ directory bundled alongside jingles.py
      2. System PATH
      3. Common Windows install locations
    """
    here = os.path.dirname(os.path.abspath(__file__))

    # 1. Bundled tools/
    bundled = os.path.join(here, 'tools', 'adb.exe')
    if os.path.isfile(bundled):
        return bundled

    # Also check tools/platform-tools/adb.exe (extracted SDK zip)
    bundled_sub = os.path.join(here, 'tools', 'platform-tools', 'adb.exe')
    if os.path.isfile(bundled_sub):
        return bundled_sub

    # 2. System PATH
    found = shutil.which('adb')
    if found:
        return found

    # 3. Common Windows install locations
    candidates = [
        r'C:\platform-tools\adb.exe',
        r'C:\adb\adb.exe',
        os.path.expanduser(r'~\platform-tools\adb.exe'),
        os.path.expanduser(r'~\AppData\Local\Android\Sdk\platform-tools\adb.exe'),
        r'C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe',
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


# ── Device listing ───────────────────────────────────────────────────────────

def list_devices(adb_path: str) -> list[dict]:
    """Return a list of connected ADB devices.

    Each entry is a dict with keys: serial, state, model, device, product.
    Only devices in 'device' state (ready) are included.
    """
    if not adb_path:
        return []
    try:
        r = subprocess.run(
            [adb_path, 'devices', '-l'],
            capture_output=True, text=True, timeout=_CMD_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    devices = []
    for line in r.stdout.strip().splitlines()[1:]:  # skip "List of devices..."
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        if state != 'device':
            continue

        info = {'serial': serial, 'state': state,
                'model': '', 'device': '', 'product': ''}
        for part in parts[2:]:
            if ':' in part:
                key, _, val = part.partition(':')
                if key in info:
                    info[key] = val
        devices.append(info)
    return devices


# ── Remote file operations ───────────────────────────────────────────────────

def _adb_shell(adb_path: str, serial: str, cmd: str,
               timeout: int = _CMD_TIMEOUT) -> tuple[bool, str]:
    """Run an ADB shell command and return (success, stdout)."""
    try:
        r = subprocess.run(
            [adb_path, '-s', serial, 'shell', cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0, r.stdout
    except subprocess.TimeoutExpired:
        return False, ''
    except (FileNotFoundError, OSError):
        return False, ''


def list_directory(adb_path: str, serial: str,
                   remote_dir: str) -> list[dict]:
    """List entries in a remote directory.

    Returns a list of dicts with keys: name, is_dir.
    Sorted: directories first, then files, both alphabetically.
    """
    # Quote the path for the shell
    quoted = shlex.quote(remote_dir.rstrip('/'))
    ok, out = _adb_shell(adb_path, serial,
                         f'ls -1p {quoted} 2>/dev/null')
    if not ok:
        return []

    entries = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line or line in ('.', '..', './', '../'):
            continue
        is_dir = line.endswith('/')
        name = line.rstrip('/')
        if name in ('.', '..'):
            continue
        entries.append({'name': name, 'is_dir': is_dir})

    # Sort: dirs first, then alpha
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    return entries


def scan_device_roms(adb_path: str, serial: str, remote_dir: str,
                     recursive: bool = True,
                     cancel_event=None) -> list[str]:
    """Scan a remote directory for ROM files.

    Returns a sorted list of remote POSIX path strings.
    """
    quoted = shlex.quote(remote_dir.rstrip('/'))
    if recursive:
        cmd = f'find {quoted} -type f 2>/dev/null'
    else:
        cmd = f'find {quoted} -maxdepth 1 -type f 2>/dev/null'

    ok, out = _adb_shell(adb_path, serial, cmd, timeout=120)
    if not ok:
        return []

    results = []
    for line in out.strip().splitlines():
        path = line.strip()
        if not path:
            continue
        if cancel_event and cancel_event.is_set():
            break
        ext = PurePosixPath(path).suffix.lower()
        if ext in SUPPORTED_EXTENSIONS:
            results.append(path)

    return sorted(results, key=lambda p: p.lower())


def get_remote_stat(adb_path: str, serial: str,
                    remote_path: str) -> dict | None:
    """Get file size and mtime for a remote file.

    Returns {'size': int, 'mtime': int} or None on failure.
    """
    quoted = shlex.quote(remote_path)
    # %s = size, %Y = mtime epoch
    ok, out = _adb_shell(adb_path, serial,
                         f'stat -c "%s %Y" {quoted} 2>/dev/null')
    if not ok or not out.strip():
        return None
    try:
        parts = out.strip().split()
        return {'size': int(parts[0]), 'mtime': int(parts[1])}
    except (ValueError, IndexError):
        return None


def pull_file(adb_path: str, serial: str, remote_path: str,
              local_path: str, timeout: int = _PULL_TIMEOUT) -> bool:
    """Pull a file from the device to a local path.

    Returns True on success.
    """
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        r = subprocess.run(
            [adb_path, '-s', serial, 'pull', remote_path, local_path],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0 and os.path.isfile(local_path)
    except subprocess.TimeoutExpired:
        # Clean up partial file
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        return False
    except (FileNotFoundError, OSError):
        return False


def push_file(adb_path: str, serial: str, local_path: str,
              remote_path: str, timeout: int = _PUSH_TIMEOUT) -> bool:
    """Push a local file to the device.

    Returns True on success.
    """
    # Ensure remote parent directory exists
    parent = str(PurePosixPath(remote_path).parent)
    quoted_parent = shlex.quote(parent)
    _adb_shell(adb_path, serial, f'mkdir -p {quoted_parent}')

    try:
        r = subprocess.run(
            [adb_path, '-s', serial, 'push', local_path, remote_path],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ── ROM cache ────────────────────────────────────────────────────────────────

class AdbRomCache:
    """Cache for ROM files pulled from an ADB device.

    Maintains a manifest mapping remote paths to local cached copies.
    Skips re-downloading files whose size and mtime haven't changed.
    """

    def __init__(self, adb_path: str, serial: str):
        self._adb = adb_path
        self._serial = serial
        self._cache_dir = os.path.join(ADB_CACHE_DIR, serial)
        os.makedirs(self._cache_dir, exist_ok=True)
        self._manifest = self._load_manifest()

    def _manifest_path(self) -> str:
        return os.path.join(self._cache_dir, '_manifest.json')

    def _load_manifest(self) -> dict:
        try:
            with open(self._manifest_path(), 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_manifest(self):
        with open(self._manifest_path(), 'w') as f:
            json.dump(self._manifest, f, indent=2)

    def _local_path_for(self, remote_path: str) -> str:
        """Deterministic local path for a remote file."""
        # Flatten the remote path into a safe local filename while
        # preserving uniqueness.  Keep the original stem + ext for
        # readability (the worker uses the stem as the MP3 title).
        posix = PurePosixPath(remote_path)
        # Use a hash of the full path to avoid collisions between
        # identically-named files in different directories.
        path_hash = abs(hash(remote_path)) % 0xFFFFFFFF
        safe_name = f'{path_hash:08x}_{posix.name}'
        # Sanitize for Windows
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', safe_name)
        return os.path.join(self._cache_dir, safe_name)

    def is_cached(self, remote_path: str) -> bool:
        """Check if a remote file is already cached and up-to-date."""
        entry = self._manifest.get(remote_path)
        if not entry:
            return False
        local_path = entry.get('local_path', '')
        if not os.path.isfile(local_path):
            return False
        # Check if remote file has changed
        stat = get_remote_stat(self._adb, self._serial, remote_path)
        if stat is None:
            return False  # Can't verify — re-pull to be safe
        return (entry.get('size') == stat['size'] and
                entry.get('mtime') == stat['mtime'])

    def ensure_local(self, remote_path: str,
                     cancel_event=None) -> str | None:
        """Return a local path for the remote ROM, pulling if needed.

        Returns None if the pull fails or is cancelled.
        """
        if cancel_event and cancel_event.is_set():
            return None

        # Check cache
        entry = self._manifest.get(remote_path)
        if entry:
            local_path = entry.get('local_path', '')
            if os.path.isfile(local_path):
                stat = get_remote_stat(self._adb, self._serial, remote_path)
                if stat and (entry.get('size') == stat['size'] and
                             entry.get('mtime') == stat['mtime']):
                    return local_path

        # Pull the file
        local_path = self._local_path_for(remote_path)
        stat = get_remote_stat(self._adb, self._serial, remote_path)

        if cancel_event and cancel_event.is_set():
            return None

        if not pull_file(self._adb, self._serial, remote_path, local_path):
            return None

        # Update manifest
        self._manifest[remote_path] = {
            'local_path': local_path,
            'size': stat['size'] if stat else 0,
            'mtime': stat['mtime'] if stat else 0,
            'pulled_at': int(time.time()),
        }
        self._save_manifest()
        return local_path

    def get_local_path(self, remote_path: str) -> str | None:
        """Return cached local path without pulling. None if not cached."""
        entry = self._manifest.get(remote_path)
        if entry and os.path.isfile(entry.get('local_path', '')):
            return entry['local_path']
        return None

    def clear(self):
        """Delete all cached files and reset the manifest."""
        import shutil as _shutil
        if os.path.isdir(self._cache_dir):
            _shutil.rmtree(self._cache_dir, ignore_errors=True)
        os.makedirs(self._cache_dir, exist_ok=True)
        self._manifest = {}
        self._save_manifest()

    def cache_size_bytes(self) -> int:
        """Return total size of cached files in bytes."""
        total = 0
        for entry in self._manifest.values():
            lp = entry.get('local_path', '')
            if os.path.isfile(lp):
                total += os.path.getsize(lp)
        return total
