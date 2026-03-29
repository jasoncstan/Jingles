"""FFmpeg-based audio converter: WAV -> trimmed, faded MP3."""
import subprocess
import os

# Output clip settings
CLIP_MAX_SECS = 6.0
CLIP_MIN_SECS = 3.0
FADE_SECS = 1.0
FADE_START = CLIP_MAX_SECS - FADE_SECS  # 5.0s


def wav_to_mp3(wav_path: str, mp3_path: str, ffmpeg: str,
               title: str = None) -> None:
    """Convert a WAV file to an MP3 clip (max 6 s, 1 s fade-out).

    Args:
        wav_path: Input WAV file path.
        mp3_path: Output MP3 file path.
        ffmpeg:   Absolute path to the ffmpeg executable.
        title:    Optional ID3 title tag to embed in the MP3.

    Raises:
        RuntimeError: if ffmpeg exits with a non-zero return code.
        FileNotFoundError: if ffmpeg executable is not found.
    """
    cmd = [
        ffmpeg, '-y',
        '-i', wav_path,
        '-t', str(CLIP_MAX_SECS),
        '-af', f'afade=t=in:d=0.03,afade=t=out:st={FADE_START}:d={FADE_SECS}',
        '-ar', '44100',
        '-ac', '2',          # upmix mono to stereo for MP3 compatibility
        '-b:a', '128k',
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

    Extracts up to (CLIP_MAX_SECS + 2) seconds to allow the converter some
    headroom. Returns True on success, False if no audio stream was found.
    """
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
