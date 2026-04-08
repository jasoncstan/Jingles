"""User-configurable settings with sensible defaults.

Settings are persisted in jingles_config.json under the 'settings' key.
Game-specific overrides live under the 'game_rules' key — a list of
{name, pattern, regex, overrides} dicts. Each consumer (converter,
extractors) calls get_for_rom(key, rom_path) to read the value that
applies to a specific ROM, with rules taking precedence over globals.

Changes from the Settings dialog take effect on the next file processed
without needing a restart.
"""
import os
import re

from utils import load_config, save_config

# ── Defaults ─────────────────────────────────────────────────────────────────
# Each entry: key -> (default value, type, label, description, group)

DEFAULTS = {
    # Output / clipping (used by emulation/fallback paths)
    'clip_max_secs': (
        6.0, float, 'Max clip duration (s)',
        'Maximum length of an emulation-captured clip.', 'Output'),
    'clip_min_secs': (
        3.0, float, 'Min clip duration (s)',
        'Minimum length before fade-out is applied.', 'Output'),
    'fade_secs': (
        1.0, float, 'Fade-out duration (s)',
        'Length of the fade-out at the end of an emulation clip.', 'Output'),
    'fade_in_secs': (
        0.03, float, 'Fade-in duration (s)',
        'Short fade-in to avoid pops at the start of clips.', 'Output'),
    'mp3_bitrate': (
        '128k', str, 'MP3 bitrate',
        'Output MP3 bitrate (e.g. 128k, 192k, 256k).', 'Output'),
    'mp3_sample_rate': (
        44100, int, 'MP3 sample rate (Hz)',
        'Output MP3 sample rate. Standard CD quality is 44100.', 'Output'),

    # RetroArch emulation
    'retroarch_capture_frames': (
        900, int, 'RetroArch capture frames',
        'Default number of emulation frames to capture (~15 s at 60 fps).',
        'RetroArch'),
    'retroarch_capture_max_multiplier': (
        3, int, 'Max retry multiplier',
        'Longest retry attempt is this many times the default capture length.',
        'RetroArch'),

    # PCSX2 (PS2)
    'ps2_turbo_boot_secs': (
        3, int, 'PS2 turbo boot duration (s)',
        'Seconds to run in turbo mode to fast-forward past logos.', 'PS2'),
    'ps2_settle_secs': (
        2, int, 'PS2 settle duration (s)',
        'Seconds to wait at normal speed before recording.', 'PS2'),
    'ps2_record_secs': (
        8, int, 'PS2 record duration (s)',
        'Length of audio capture from a running PS2 game.', 'PS2'),
}


def get(key: str):
    """Return the current global value for a setting (override or default).

    Use get_for_rom() instead when a ROM path is available — it also
    applies any matching game-specific rules.
    """
    default = DEFAULTS[key][0]
    cfg = load_config()
    settings = cfg.get('settings', {})
    val = settings.get(key, default)
    type_ = DEFAULTS[key][1]
    try:
        return type_(val)
    except (TypeError, ValueError):
        return default


def get_for_rom(key: str, rom_path: str = None):
    """Return the value of a setting for a specific ROM path.

    Checks game-specific rules first (in order, first match wins),
    then falls back to the global setting / default.
    """
    if rom_path:
        rule = _matching_rule(rom_path)
        if rule:
            overrides = rule.get('overrides', {})
            if key in overrides:
                type_ = DEFAULTS[key][1]
                try:
                    return type_(overrides[key])
                except (TypeError, ValueError):
                    pass
    return get(key)


def _matching_rule(rom_path: str) -> dict:
    """Return the first matching game rule for the given ROM path, or None.

    A rule matches when:
      - Its filename pattern matches the ROM basename, AND
      - Its platforms list is empty (any) OR contains the ROM's platform.
    """
    rules = get_rules()
    if not rules:
        return None

    name = os.path.basename(rom_path)
    rom_platform = _platform_for(rom_path)

    for rule in rules:
        pattern = rule.get('pattern', '').strip()
        if not pattern:
            continue

        # Platform filter (empty list / missing field = match any platform)
        platforms = rule.get('platforms', [])
        if platforms and rom_platform not in platforms:
            continue

        try:
            if rule.get('regex', False):
                if re.search(pattern, name, re.IGNORECASE):
                    return rule
            else:
                if pattern.lower() in name.lower():
                    return rule
        except re.error:
            continue
    return None


def _platform_for(rom_path: str) -> str:
    """Return the platform name for a ROM path, or '' on failure."""
    try:
        from utils import get_platform
        return get_platform(rom_path)
    except Exception:
        return ''


def get_rules() -> list:
    """Return the list of saved game-specific rules."""
    cfg = load_config()
    rules = cfg.get('game_rules', [])
    return rules if isinstance(rules, list) else []


def save_rules(rules: list):
    """Persist the list of game-specific rules."""
    save_config(game_rules=rules)


# ── Export / Import ─────────────────────────────────────────────────────────

EXPORT_VERSION = 1


def export_rules(path: str, rules: list = None) -> int:
    """Write the given rules (or all current rules) to a JSON file.

    Returns the number of rules exported.
    """
    import json
    if rules is None:
        rules = get_rules()
    payload = {
        'version': EXPORT_VERSION,
        'rules': rules,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    return len(rules)


def load_rules_file(path: str) -> list:
    """Read a rules file and return a list of valid rule dicts.

    Accepts:
      - {"version": N, "rules": [...]} (preferred export format)
      - A bare list of rule dicts

    Raises ValueError on a malformed file. Skips entries that don't
    look like valid rules.
    """
    import json
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        raw_rules = data.get('rules', [])
    elif isinstance(data, list):
        raw_rules = data
    else:
        raise ValueError('Unrecognised rules file format')

    if not isinstance(raw_rules, list):
        raise ValueError('Rules entry is not a list')

    valid = []
    for r in raw_rules:
        if not isinstance(r, dict):
            continue
        name = str(r.get('name', '')).strip()
        pattern = str(r.get('pattern', '')).strip()
        if not name or not pattern:
            continue
        overrides = r.get('overrides', {})
        if not isinstance(overrides, dict):
            overrides = {}
        clean_overrides = {k: v for k, v in overrides.items() if k in DEFAULTS}

        platforms = r.get('platforms', [])
        if not isinstance(platforms, list):
            platforms = []
        platforms = [str(p) for p in platforms if p]

        valid.append({
            'name': name,
            'pattern': pattern,
            'regex': bool(r.get('regex', False)),
            'platforms': platforms,
            'overrides': clean_overrides,
        })
    return valid


def merge_rules(imported: list) -> tuple[int, int]:
    """Merge imported rules into the current saved rules.

    Rules with names that already exist are renamed with a numeric
    suffix (e.g. "Pokemon games (2)") to keep both.

    Returns (added_count, renamed_count).
    """
    current = get_rules()
    existing_names = {r.get('name', '') for r in current}

    added = 0
    renamed = 0
    for rule in imported:
        name = rule.get('name', '')
        if name in existing_names:
            # Find a unique name with a numeric suffix
            n = 2
            new_name = f'{name} ({n})'
            while new_name in existing_names:
                n += 1
                new_name = f'{name} ({n})'
            rule = dict(rule)
            rule['name'] = new_name
            renamed += 1
        existing_names.add(rule['name'])
        current.append(rule)
        added += 1

    save_rules(current)
    return added, renamed


def replace_rules(imported: list) -> int:
    """Replace all current rules with the imported list. Returns count."""
    save_rules(imported)
    return len(imported)


def get_all() -> dict:
    """Return a dict of all current settings (overrides merged with defaults)."""
    cfg = load_config()
    settings = cfg.get('settings', {})
    result = {}
    for key, (default, type_, *_) in DEFAULTS.items():
        try:
            result[key] = type_(settings.get(key, default))
        except (TypeError, ValueError):
            result[key] = default
    return result


def save(values: dict):
    """Persist a dict of setting values to jingles_config.json."""
    cfg = load_config()
    settings = cfg.get('settings', {})
    for key, val in values.items():
        if key in DEFAULTS:
            settings[key] = val
    save_config(settings=settings)


def reset_to_defaults():
    """Restore all settings to their default values."""
    save_config(settings={})
