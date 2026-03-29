"""Nintendo DS / DSi banner sound extractor.

Only DSi-enhanced ROMs carry banner audio. These ROMs have banner version
0x0103 (DSi). Standard NDS ROMs (version 0x0001-0x0003) have no audio in
their banners and return None.

Banner audio format:
  - 0x4000 bytes of IMA-ADPCM (4-bit, mono, ~16384 Hz)
  - Starts at banner_offset + 0x1240
  - Header: 4 bytes (s16le initial sample, u8 step index, u8 padding)
  - Yields approximately 2 seconds of audio; looped to meet minimum duration
"""
import struct
from extractors.base import BaseExtractor
from audio.ima_adpcm import decode_ima_adpcm
from audio.wav_utils import loop_to_min_duration

# Offset within the NDS ROM header that stores the banner offset
_BANNER_PTR_OFF = 0x068

# DSi-enhanced banner version that includes sound data
_DSI_BANNER_VER = 0x0103

# Offset within the banner where the sound data begins
_SOUND_OFF = 0x1240
_SOUND_SIZE = 0x4000

# Sample rate used for DSi banner audio
_SAMPLE_RATE = 16384


class NdsExtractor(BaseExtractor):
    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        with open(rom_path, 'rb') as f:
            # Read the NDS header (at least up to the banner pointer)
            header = f.read(0x180)
            if len(header) < 0x180:
                return None

            banner_off = struct.unpack_from('<I', header, _BANNER_PTR_OFF)[0]
            if banner_off == 0:
                return None

            # Read the two-byte banner version
            f.seek(banner_off)
            ver_bytes = f.read(2)
            if len(ver_bytes) < 2:
                return None
            version = struct.unpack_from('<H', ver_bytes, 0)[0]

            if version != _DSI_BANNER_VER:
                return None  # No audio in non-DSi banners

            # Read the sound data block
            f.seek(banner_off + _SOUND_OFF)
            sound_data = f.read(_SOUND_SIZE)

        if len(sound_data) < 8:
            return None

        samples = decode_ima_adpcm(sound_data)
        if not samples:
            return None

        # Loop to reach at least 3 seconds (banner audio is ~2 s)
        samples = loop_to_min_duration(samples, _SAMPLE_RATE, 1)
        return samples, _SAMPLE_RATE, 1
