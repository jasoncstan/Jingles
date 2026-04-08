"""FFmpeg-based audio converter: WAV -> trimmed, faded MP3."""
import subprocess
import os

import settings


def _get_clip_settings(rom_path: str = None):
    """Read current clip-related settings, with optional per-ROM overrides."""
    return (
        settings.get_for_rom('clip_max_secs', rom_path),
        settings.get_for_rom('clip_min_secs', rom_path),
        settings.get_for_rom('fade_secs', rom_path),
        settings.get_for_rom('fade_in_secs', rom_path),
        settings.get_for_rom('mp3_bitrate', rom_path),
        settings.get_for_rom('mp3_sample_rate', rom_path),
    )


# Module-level constants kept for backwards compatibility (some callers
# read these directly).  They reflect the current saved settings.
def _refresh_constants():
    global CLIP_MAX_SECS, CLIP_MIN_SECS, FADE_SECS, FADE_START
    CLIP_MAX_SECS = settings.get('clip_max_secs')
    CLIP_MIN_SECS = settings.get('clip_min_secs')
    FADE_SECS = settings.get('fade_secs')
    FADE_START = max(0.0, CLIP_MAX_SECS - FADE_SECS)


_refresh_constants()


def wav_to_mp3(wav_path: str, mp3_path: str, ffmpeg: str,
               title: str = None, trim: bool = True,
               rom_path: str = None) -> None:
    """Convert a WAV file to an MP3.

    Args:
        wav_path: Input WAV file path.
        mp3_path: Output MP3 file path.
        ffmpeg:   Absolute path to the ffmpeg executable.
        title:    Optional ID3 title tag to embed in the MP3.
        trim:     If True (default), clip to max length with fade-out.
                  If False, preserve the full duration with no effects.
        rom_path: Optional source ROM path used to look up per-game
                  setting overrides.

    Raises:
        RuntimeError: if ffmpeg exits with a non-zero return code.
        FileNotFoundError: if ffmpeg executable is not found.
    """
    _refresh_constants()
    clip_max, _clip_min, fade_out, fade_in, bitrate, sample_rate = \
        _get_clip_settings(rom_path)
    fade_start = max(0.0, clip_max - fade_out)

    cmd = [
        ffmpeg, '-y',
        '-i', wav_path,
    ]
    if trim:
        cmd += [
            '-t', str(clip_max),
            '-af', f'afade=t=in:d={fade_in},'
                   f'afade=t=out:st={fade_start}:d={fade_out}',
        ]
    cmd += [
        '-ar', str(sample_rate),
        '-ac', '2',          # upmix mono to stereo for MP3 compatibility
        '-b:a', str(bitrate),
    ]
    if title:
        cmd += ['-metadata', f'title={title}']
    cmd.append(mp3_path)
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0:
        err = result.stderr.decode('utf-8', errors='replace')
        raise RuntimeError(f'ffmpeg conversion failed: {err[-500:]}')


def generic_extract_to_wav(rom_path: str, wav_path: str, ffmpeg: str) -> bool:
    """Use FFmpeg to extract the first audio stream from a ROM to a WAV file.

    Extracts up to (clip_max + 2) seconds to allow the converter some
    headroom. Returns True on success, False if no audio stream was found.
    """
    _refresh_constants()
    cmd = [
        ffmpeg, '-y',
        '-i', rom_path,
        '-map', '0:a:0',
        '-t', str(CLIP_MAX_SECS + 2),
        '-acodec', 'pcm_s16le',
        '-ar', '44100',
        wav_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=90)
        if result.returncode == 0 and os.path.exists(wav_path):
            return os.path.getsize(wav_path) > 44  # more than just the WAV header
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
