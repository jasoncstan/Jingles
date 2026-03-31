"""Nintendo Wii U boot sound extractor.

Wii U games store a boot sound (played when launching from the HOME Menu)
as bootSound.btsnd inside the /meta/ directory.

The BTSND file contains raw PCM audio: 48000 Hz, 16-bit signed big-endian,
stereo (2 channels).  There is no header — the entire file is audio data.

Supported input formats:
  - Decrypted Wii U game folders (code/content/meta/ structure)
    Jingles scans for meta/bootSound.btsnd as a virtual "ROM".
  - Decrypted WUX/WUD disc images (FST search for bootSound.btsnd)
  - Encrypted disc images are NOT supported (content is AES-encrypted).
"""
import os
import struct

from extractors.base import BaseExtractor

BTSND_RATE = 48000
BTSND_CHANNELS = 2

# For disc image scanning
_MAX_SEARCH_BYTES = 25 * 1024 * 1024 * 1024  # full disc
_CHUNK_SIZE = 4 * 1024 * 1024
_TARGET = b'bootSound.btsnd\x00'


class WiiUExtractor(BaseExtractor):
    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        # 1. Check if rom_path IS a bootSound.btsnd file directly
        if os.path.basename(rom_path).lower() == 'bootsound.btsnd':
            return self._read_btsnd_file(rom_path)

        # 2. Check if rom_path is inside a Wii U game folder with meta/
        btsnd = self._find_btsnd_in_folder(rom_path)
        if btsnd is not None:
            return self._decode_btsnd(btsnd)

        # 3. Try as a disc image (WUX/WUD)
        return self._extract_from_disc(rom_path)

    def _read_btsnd_file(self, btsnd_path: str):
        """Read a bootSound.btsnd file directly."""
        with open(btsnd_path, 'rb') as f:
            data = f.read()
        if len(data) < BTSND_CHANNELS * 2:
            return None
        return self._decode_btsnd(data)

    def _find_btsnd_in_folder(self, rom_path: str) -> bytes | None:
        """Look for meta/bootSound.btsnd relative to the ROM's directory.

        Handles these structures:
          GameFolder/meta/bootSound.btsnd   (rom_path points to a file
              inside GameFolder or to GameFolder itself)
          GameFolder/code/ + content/ + meta/
        """
        if os.path.isdir(rom_path):
            game_dir = rom_path
        else:
            game_dir = os.path.dirname(rom_path)

        # Walk up a couple levels looking for a sibling meta/ directory
        for _ in range(3):
            btsnd_path = os.path.join(game_dir, 'meta', 'bootSound.btsnd')
            if os.path.isfile(btsnd_path):
                with open(btsnd_path, 'rb') as f:
                    return f.read()
            # Also check case-insensitive
            meta_dir = os.path.join(game_dir, 'meta')
            if os.path.isdir(meta_dir):
                for name in os.listdir(meta_dir):
                    if name.lower() == 'bootsound.btsnd':
                        with open(os.path.join(meta_dir, name), 'rb') as f:
                            return f.read()
            game_dir = os.path.dirname(game_dir)

        return None

    def _extract_from_disc(self, rom_path: str):
        """Try extracting from a decrypted WUX/WUD disc image."""
        from formats.wii_disc import WiiDisc

        with WiiDisc(rom_path) as disc:
            # Skip if this is actually a Wii or GameCube disc
            hdr = disc.read_virtual(0, 0x20)
            if len(hdr) < 0x20:
                return None
            wii_magic = struct.unpack_from('>I', hdr, 0x18)[0]
            gcn_magic = struct.unpack_from('>I', hdr, 0x1C)[0]
            if wii_magic == WiiDisc.WII_MAGIC or gcn_magic == WiiDisc.GCN_MAGIC:
                return None

            btsnd_data = self._find_boot_sound_in_disc(disc)
            if btsnd_data is None or len(btsnd_data) < BTSND_CHANNELS * 2:
                return None

            return self._decode_btsnd(btsnd_data)

    def _find_boot_sound_in_disc(self, disc) -> bytes | None:
        """Search a decrypted disc for bootSound.btsnd via FST scanning."""
        overlap = len(_TARGET)
        offset = 0
        while offset < _MAX_SEARCH_BYTES:
            chunk = disc.read_virtual(offset, _CHUNK_SIZE)
            if not chunk:
                break
            pos = chunk.find(_TARGET)
            if pos >= 0:
                result = self._extract_from_fst(disc, offset + pos)
                if result is not None:
                    return result
            offset += len(chunk) - overlap
        return None

    def _extract_from_fst(self, disc, boot_sound_str_pos: int) -> bytes | None:
        """Given the disc offset of the string, find FST root and extract."""
        lookback = 2 * 1024 * 1024
        search_start = max(0, boot_sound_str_pos - lookback)
        search_len = boot_sound_str_pos - search_start + 1024
        data = disc.read_virtual(search_start, search_len)
        if not data:
            return None

        str_rel = boot_sound_str_pos - search_start

        for i in range(str_rel - 12, -1, -12):
            if i + 12 > len(data):
                continue
            if (data[i] == 1 and data[i + 1:i + 4] == b'\x00\x00\x00'
                    and data[i + 4:i + 8] == b'\x00\x00\x00\x00'):
                num_entries = struct.unpack_from('>I', data, i + 8)[0]
                if num_entries < 2 or num_entries > 100_000:
                    continue
                str_table_rel = i + num_entries * 12
                if str_table_rel <= str_rel:
                    fst_disc_off = search_start + i
                    return self._parse_fst_for_btsnd(
                        disc, data, i, num_entries, fst_disc_off, search_start)
        return None

    def _parse_fst_for_btsnd(self, disc, data, fst_local_off, num_entries,
                              fst_disc_off, search_start):
        """Parse FST entries to locate and read bootSound.btsnd."""
        str_table_start = fst_local_off + num_entries * 12
        fst_end = str_table_start + 256 * 1024
        if fst_end > len(data):
            data = disc.read_virtual(search_start, fst_end)

        for e_idx in range(1, num_entries):
            e = fst_local_off + e_idx * 12
            if e + 12 > len(data):
                break
            type_name = struct.unpack_from('>I', data, e)[0]
            if (type_name >> 24) != 0:
                continue
            name_off = type_name & 0xFFFFFF
            name_pos = str_table_start + name_off
            if name_pos >= len(data):
                continue
            name_end = data.find(b'\x00', name_pos)
            if name_end < 0:
                continue
            name = data[name_pos:name_end].decode('ascii', errors='ignore')
            if name.lower() != 'bootsound.btsnd':
                continue

            file_off_raw = struct.unpack_from('>I', data, e + 4)[0]
            file_size = struct.unpack_from('>I', data, e + 8)[0]
            if file_size < 100 or file_size > 10 * 1024 * 1024:
                continue

            for abs_off in [fst_disc_off + file_off_raw,
                            file_off_raw,
                            fst_disc_off + file_off_raw * 4,
                            file_off_raw * 0x8000]:
                if abs_off < 0:
                    continue
                try:
                    btsnd = disc.read_virtual(abs_off, file_size)
                    if len(btsnd) == file_size and self._looks_like_pcm(btsnd):
                        return btsnd
                except Exception:
                    continue
        return None

    @staticmethod
    def _looks_like_pcm(data: bytes) -> bool:
        """Heuristic check if data looks like 16-bit big-endian PCM audio."""
        if len(data) < 100:
            return False
        if data[:256] == b'\x00' * min(256, len(data)):
            return False
        extreme = 0
        for i in range(0, min(len(data), 2000), 2):
            val = struct.unpack_from('>h', data, i)[0]
            if abs(val) > 30000:
                extreme += 1
        sample_count = min(len(data), 2000) // 2
        return extreme < sample_count * 0.5

    @staticmethod
    def _decode_btsnd(data: bytes):
        """Decode raw big-endian PCM to a list of interleaved s16 samples."""
        num_samples = len(data) // 2
        samples = list(struct.unpack(f'>{num_samples}h', data[:num_samples * 2]))
        return samples, BTSND_RATE, BTSND_CHANNELS
