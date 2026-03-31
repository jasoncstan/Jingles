"""Utility functions: FFmpeg detection, filename sanitization, and config persistence."""
import os
import shutil
import re
import json
from pathlib import Path

APP_DIR     = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE = os.path.join(APP_DIR, 'output')
CONFIG_FILE = os.path.join(APP_DIR, 'jingles_config.json')

# ROM file extensions that Jingles will scan for
SUPPORTED_EXTENSIONS = {
    # ── Nintendo ──────────────────────────────────────────────────────────────
    '.nes', '.fds',                              # NES / Famicom Disk
    '.sfc', '.smc', '.fig',                      # SNES / Sufami Turbo
    '.gb', '.gbc',                               # Game Boy / Color
    '.gba',                                      # Game Boy Advance
    '.n64', '.z64', '.v64',                      # Nintendo 64
    '.nds', '.dsi',                              # Nintendo DS / DSi
    '.3ds', '.cci', '.cia',                      # Nintendo 3DS
    '.vb', '.vboy',                              # Virtual Boy
    '.min',                                      # Pokemon Mini
    '.gcm', '.gcz',                              # GameCube
    '.iso',                                      # GameCube / Wii / PS1 / PS2 / PSP disc
    '.wbfs', '.wia', '.rvz',                       # Wii alternate formats
    '.wux', '.wud',                                # Wii U disc formats
    '.btsnd',                                      # Wii U boot sound (from decrypted game folder)
    '.wad',                                      # WiiWare
    '.nsp', '.xci',                              # Nintendo Switch
    # ── Sega ──────────────────────────────────────────────────────────────────
    '.sg',                                       # SG-1000
    '.sms',                                      # Master System
    '.gg',                                       # Game Gear
    '.md', '.gen',                               # Genesis / Mega Drive
    '.32x',                                      # Sega 32X
    '.chd',                                      # CD-based (Sega CD, Saturn, PS1, etc.)
    '.cue',                                      # Cue sheet (Sega CD, Saturn, PS1)
    # ── NEC ───────────────────────────────────────────────────────────────────
    '.pce',                                      # PC Engine / TurboGrafx-16
    '.sgx',                                      # SuperGrafx
    # ── Atari ─────────────────────────────────────────────────────────────────
    '.a26',                                      # Atari 2600
    '.bin',                                      # Atari 2600 / raw binary
    '.a52',                                      # Atari 5200
    '.a78',                                      # Atari 7800
    '.lnx',                                      # Atari Lynx
    '.j64',                                      # Atari Jaguar
    '.st',                                       # Atari ST
    # ── Other consoles ────────────────────────────────────────────────────────
    '.col',                                      # ColecoVision
    '.int',                                      # Intellivision
    '.vec',                                      # Vectrex
    '.ws', '.wsc',                               # WonderSwan / Color
    '.ngp', '.ngc',                              # Neo Geo Pocket / Color
    '.o2',                                       # Magnavox Odyssey 2
    '.chf',                                      # Fairchild Channel F
    # ── Computers ─────────────────────────────────────────────────────────────
    '.dsk',                                      # Amstrad CPC / MSX
    '.rom',                                      # MSX / MSX2
    '.d64', '.t64',                              # Commodore 64
    '.crt',                                      # Commodore 64 cartridge
    '.prg',                                      # Commodore 64 / VIC-20
    # ── Sony ──────────────────────────────────────────────────────────────────
    '.pbp',                                      # PSP
    '.cso',                                      # PSP compressed
    # ── Chip music rip formats (FFmpeg + libgme) ─────────────────────────────
    '.vgm', '.vgz',                              # VGM / VGZ (Sega, SNK, etc.)
    '.spc',                                      # SNES SPC700
    '.nsf', '.nsfe',                             # NES / Famicom
    '.gbs',                                      # Game Boy / Color
    '.gsf', '.minigsf',                          # GBA
    '.gym',                                      # Sega Genesis / Mega Drive
    '.hes',                                      # PC Engine / TurboGrafx
    '.kss',                                      # MSX / SMS / GG
    '.sap',                                      # Atari
    '.ay',                                       # ZX Spectrum / Amstrad
    '.psf', '.psf2', '.minipsf', '.minipsf2',    # PlayStation 1 / 2
    '.ssf', '.minissf',                          # Sega Saturn
    '.dsf', '.minidsf',                          # Dreamcast
    # ── Archives ──────────────────────────────────────────────────────────────
    '.zip',                                      # ZIP archive
    '.7z',                                       # 7-Zip archive
}

# Human-readable platform names keyed by extension
PLATFORM_NAMES = {
    # Nintendo
    '.nes': 'NES',
    '.fds': 'Famicom Disk',
    '.sfc': 'SNES',
    '.smc': 'SNES',
    '.fig': 'SNES',
    '.gb':  'Game Boy',
    '.gbc': 'Game Boy Color',
    '.gba': 'Game Boy Advance',
    '.n64': 'Nintendo 64',
    '.z64': 'Nintendo 64',
    '.v64': 'Nintendo 64',
    '.nds': 'Nintendo DS',
    '.dsi': 'Nintendo DSi',
    '.3ds': 'Nintendo 3DS',
    '.cci': 'Nintendo 3DS',
    '.cia': '3DS CIA',
    '.vb':  'Virtual Boy',
    '.vboy': 'Virtual Boy',
    '.min': 'Pokemon Mini',
    '.gcm': 'GameCube',
    '.gcz': 'GameCube',
    '.wbfs': 'Wii',
    '.wia': 'Wii',
    '.rvz': 'Wii',
    '.wux': 'Wii U',
    '.wud': 'Wii U',
    '.btsnd': 'Wii U',
    '.wad': 'WiiWare',
    '.nsp': 'Nintendo Switch',
    '.xci': 'Nintendo Switch',
    # Sega
    '.sg':  'SG-1000',
    '.sms': 'Master System',
    '.gg':  'Game Gear',
    '.md':  'Genesis',
    '.gen': 'Genesis',
    '.32x': 'Sega 32X',
    # NEC
    '.pce': 'PC Engine',
    '.sgx': 'SuperGrafx',
    # Atari
    '.a26': 'Atari 2600',
    '.a52': 'Atari 5200',
    '.a78': 'Atari 7800',
    '.lnx': 'Atari Lynx',
    '.j64': 'Atari Jaguar',
    '.st':  'Atari ST',
    # Other consoles
    '.col': 'ColecoVision',
    '.int': 'Intellivision',
    '.vec': 'Vectrex',
    '.ws':  'WonderSwan',
    '.wsc': 'WonderSwan Color',
    '.ngp': 'Neo Geo Pocket',
    '.ngc': 'Neo Geo Pocket Color',
    '.o2':  'Odyssey 2',
    '.chf': 'Fairchild Channel F',
    # Computers
    '.dsk': 'Amstrad CPC',
    '.rom': 'MSX',
    '.d64': 'Commodore 64',
    '.t64': 'Commodore 64',
    '.crt': 'Commodore 64',
    '.prg': 'Commodore 64',
    # Sony
    '.cso': 'PSP',
    '.pbp': 'PSP',
    '.iso': 'Disc Image',
    '.chd': 'CHD Disc',
    '.cue': 'Disc Image',
    '.bin': 'CD Image',
    # Chip music
    '.vgm':     'VGM Music',
    '.vgz':     'VGM Music',
    '.spc':     'SNES SPC',
    '.nsf':     'NES NSF',
    '.nsfe':    'NES NSFe',
    '.gbs':     'Game Boy GBS',
    '.gsf':     'GBA GSF',
    '.minigsf': 'GBA GSF',
    '.gym':     'Genesis GYM',
    '.hes':     'PC Engine HES',
    '.kss':     'MSX KSS',
    '.sap':     'Atari SAP',
    '.ay':      'ZX Spectrum AY',
    '.psf':     'PlayStation PSF',
    '.psf2':    'PlayStation 2 PSF2',
    '.minipsf': 'PlayStation PSF',
    '.minipsf2':'PlayStation 2 PSF2',
    '.ssf':     'Saturn SSF',
    '.minissf': 'Saturn SSF',
    '.dsf':     'Dreamcast DSF',
    '.minidsf': 'Dreamcast DSF',
    # Archives
    '.zip': 'ZIP Archive',
    '.7z':  '7-Zip Archive',
}


def find_ffmpeg() -> str:
    """Return the path to the ffmpeg executable, or None if not found.

    Search order:
      1. tools/ directory bundled alongside jingles.py
      2. System PATH
      3. Common Windows install locations
    """
    # 1. Bundled tools/ directory (highest priority)
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, 'tools', 'ffmpeg.exe')
    if os.path.isfile(bundled):
        return bundled

    # 2. System PATH
    found = shutil.which('ffmpeg')
    if found:
        return found

    # 3. Common Windows install locations
    candidates = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
        os.path.expanduser(r'~\ffmpeg\bin\ffmpeg.exe'),
        os.path.expanduser(r'~\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def find_7z() -> str:
    """Return the path to 7z.exe or 7za.exe, or None if not found.

    Search order:
      1. tools/ directory bundled alongside jingles.py
      2. System PATH
      3. Common Windows install locations
    """
    here = os.path.dirname(os.path.abspath(__file__))

    # Bundled tools/ directory
    for name in ('7z.exe', '7za.exe'):
        bundled = os.path.join(here, 'tools', name)
        if os.path.isfile(bundled):
            return bundled

    # System PATH
    for name in ('7z', '7za'):
        found = shutil.which(name)
        if found:
            return found

    # Common Windows install locations
    candidates = [
        r'C:\Program Files\7-Zip\7z.exe',
        r'C:\Program Files (x86)\7-Zip\7z.exe',
        os.path.expanduser(r'~\AppData\Local\Programs\7-Zip\7z.exe'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def find_retroarch() -> tuple:
    """Return (retroarch_path, cores_dir) or (None, None) if not found.

    Search order:
      1. tools/retroarch.exe  (direct placement)
      2. Any subdirectory of tools/ that contains retroarch.exe
         (handles extracting the RetroArch .7z directly into tools/)
      3. System PATH
      4. Common Windows install locations
    """
    here = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(here, 'tools')

    def _resolve(exe_path: str) -> tuple:
        """Given a retroarch.exe path, return (exe, cores_dir)."""
        ra_dir = os.path.dirname(exe_path)
        cores = os.path.join(ra_dir, 'cores')
        if not os.path.isdir(cores):
            # Fall back to tools/cores/ if no sibling cores/ exists
            cores = os.path.join(tools_dir, 'cores')
        os.makedirs(cores, exist_ok=True)
        return exe_path, cores

    # 1. Direct placement: tools/retroarch.exe
    direct = os.path.join(tools_dir, 'retroarch.exe')
    if os.path.isfile(direct):
        return _resolve(direct)

    # 2. Subdirectory of tools/ (e.g. tools/RetroArch-Win64/retroarch.exe)
    if os.path.isdir(tools_dir):
        for entry in os.listdir(tools_dir):
            sub = os.path.join(tools_dir, entry)
            if os.path.isdir(sub):
                candidate = os.path.join(sub, 'retroarch.exe')
                if os.path.isfile(candidate):
                    return _resolve(candidate)

    # 3. System PATH
    found = shutil.which('retroarch')
    if found:
        return _resolve(found)

    # 4. Common Windows install locations
    candidates = [
        r'C:\RetroArch\retroarch.exe',
        r'C:\RetroArch-Win64\retroarch.exe',
        r'C:\Program Files\RetroArch\retroarch.exe',
        os.path.expanduser(r'~\AppData\Roaming\RetroArch\retroarch.exe'),
        os.path.expanduser(r'~\RetroArch\retroarch.exe'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return _resolve(path)

    return None, None


def find_dolphintool() -> str:
    """Return the path to DolphinTool.exe, or None if not found.

    DolphinTool ships with Dolphin Emulator and can convert RVZ/WIA to ISO.
    Search order:
      1. tools/ directory bundled alongside jingles.py
      2. System PATH
      3. Common Windows install locations
    """
    here = os.path.dirname(os.path.abspath(__file__))

    for name in ('DolphinTool.exe', 'dolphintool.exe', 'DolphinTool'):
        bundled = os.path.join(here, 'tools', name)
        if os.path.isfile(bundled):
            return bundled
        found = shutil.which(name)
        if found:
            return found

    # Check Dolphin install directories
    candidates = [
        r'C:\Program Files\Dolphin\DolphinTool.exe',
        r'C:\Program Files (x86)\Dolphin\DolphinTool.exe',
        os.path.expanduser(r'~\AppData\Local\Dolphin\DolphinTool.exe'),
        os.path.expanduser(r'~\AppData\Local\Programs\Dolphin\DolphinTool.exe'),
    ]

    # Also check subdirectories of tools/ (e.g. tools/Dolphin/DolphinTool.exe)
    tools_dir = os.path.join(here, 'tools')
    if os.path.isdir(tools_dir):
        for entry in os.listdir(tools_dir):
            sub = os.path.join(tools_dir, entry)
            if os.path.isdir(sub):
                candidate = os.path.join(sub, 'DolphinTool.exe')
                if os.path.isfile(candidate):
                    return candidate

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def find_vgmstream() -> str:
    """Return the path to vgmstream-cli.exe, or None if not found.

    Search order:
      1. tools/ directory bundled alongside jingles.py
      2. System PATH
    Download: https://github.com/vgmstream/vgmstream/releases
    """
    here = os.path.dirname(os.path.abspath(__file__))

    for name in ('vgmstream-cli.exe', 'vgmstream64-cli.exe', 'vgmstream-cli', 'vgmstream64-cli'):
        bundled = os.path.join(here, 'tools', name)
        if os.path.isfile(bundled):
            return bundled
        found = shutil.which(name)
        if found:
            return found

    return None


def load_config() -> dict:
    """Load persistent app config from jingles_config.json."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(**kwargs):
    """Merge kwargs into the persistent config and write to disk."""
    data = load_config()
    data.update(kwargs)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# Ambiguous extensions shared by multiple systems — resolved by folder name.
_AMBIGUOUS_EXTS = {'.chd', '.iso', '.cue', '.bin'}

_FOLDER_PLATFORM_HINTS = [
    ('playstation portable', 'PlayStation Portable'),
    ('playstation 2',  'PlayStation 2'),
    ('ps2',            'PlayStation 2'),
    ('psp',            'PlayStation Portable'),
    ('playstation',    'PlayStation'),
    ('ps1',            'PlayStation'),
    ('psx',            'PlayStation'),
    ('saturn',         'Sega Saturn'),
    ('sega cd',        'Sega CD'),
    ('mega cd',        'Sega CD'),
    ('3do',            'Panasonic 3DO'),
    ('cd-i',           'Philips CD-i'),
    ('cdi',            'Philips CD-i'),
    ('pc engine',      'PC Engine CD'),
    ('turbografx',     'TurboGrafx-CD'),
    ('dreamcast',      'Dreamcast'),
    ('gamecube',       'GameCube'),
]


def _detect_platform(rom_path: str, ext: str) -> str:
    """Detect platform from extension, using folder name for ambiguous types."""
    if ext in _AMBIGUOUS_EXTS:
        folder = Path(rom_path).parent.name.lower()
        for keyword, platform in _FOLDER_PLATFORM_HINTS:
            if keyword in folder:
                return platform
    return PLATFORM_NAMES.get(ext, 'Unknown')


def get_mp3_path(rom_path: str, inner_ext: str) -> str:
    """Return the output MP3 path for a ROM inside output/<Platform>/.

    Args:
        rom_path:  Path to the original ROM (or archive) file — used for stem.
        inner_ext: Extension of the actual ROM (after archive extraction).
                   Used to determine the platform subfolder name.
    """
    platform = _detect_platform(rom_path, inner_ext.lower())
    stem = game_stem(rom_path, inner_ext.lower())
    out_dir = os.path.join(OUTPUT_BASE, platform)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, stem + '.mp3')


def game_stem(rom_path: str, ext: str = None) -> str:
    """Return the game name stem for a ROM path.

    For .btsnd files (Wii U decrypted folders), uses the game folder name
    (parent of meta/) instead of the filename 'bootSound'.
    """
    if ext is None:
        ext = os.path.splitext(rom_path)[1].lower()
    if ext == '.btsnd':
        # meta/bootSound.btsnd → use the game folder name (parent of meta/)
        meta_dir = Path(rom_path).parent
        if meta_dir.name.lower() == 'meta':
            game_dir_name = meta_dir.parent.name
            return re.sub(r'[\\/:*?"<>|]', '_', game_dir_name).strip()
    return safe_stem(rom_path)


def get_platform(path: str) -> str:
    """Return a human-readable platform name for a ROM file extension."""
    ext = os.path.splitext(path)[1].lower()
    return _detect_platform(path, ext)


def safe_stem(path: str) -> str:
    """Return the filename stem, sanitized for use as an output filename.

    Strips characters that are invalid on Windows/macOS/Linux filesystems.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    # Replace illegal characters with underscore
    stem = re.sub(r'[\\/:*?"<>|]', '_', stem)
    return stem.strip()
