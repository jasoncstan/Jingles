"""Generic FFmpeg-based audio extractor (fallback for all ROM types).

Uses FFmpeg to probe and extract the first audio stream from any file.
This is the last resort when no format-specific extractor succeeds.
"""
import subprocess
import os
from extractors.base import BaseExtractor


class GenericExtractor(BaseExtractor):
    """Wraps FFmpeg to extract audio directly to a WAV file.

    Unlike the format-specific extractors, this one does NOT return a
    (samples, rate, channels) tuple. Instead it writes a WAV file directly
    and returns True/False. The worker handles this special case.
    """

    def extract(self, rom_path: str):
        """Not used directly; call extract_to_wav() instead."""
        return None

    def extract_to_wav(self, rom_path: str, wav_path: str, ffmpeg: str) -> bool:
        """Extract the first audio stream from rom_path into wav_path.

        Returns True if a non-empty WAV was written, False otherwise.
        """
        from audio.converter import CLIP_MAX_SECS

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
                return os.path.getsize(wav_path) > 44
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return False
