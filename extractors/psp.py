"""Sony PSP banner sound extractor.

Extracts SND0.AT3 (the XMB hover sound) from PSP game images:
  .iso  — UMD disc image (ISO9660), SND0.AT3 in PSP_GAME/ directory
  .cso  — CISO compressed disc image (decompressed on-the-fly)
  .pbp  — PBP container (PSN games), SND0.AT3 at header offset index 5

The AT3 (ATRAC3) file is decoded to WAV by FFmpeg.
"""
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from extractors.base import BaseExtractor
from utils import find_ffmpeg

# PBP header: "\x00PBP" magic, version u32, then 8 x u32 section offsets
# Index 5 = SND0.AT3, index 6 = DATA.PSP (next section = end of SND0)
_PBP_MAGIC = b'\x00PBP'
_PBP_SND0_IDX = 5


class PspExtractor(BaseExtractor):
    """Extract PSP banner sound (SND0.AT3) and return decoded samples."""

    def __init__(self, ffmpeg_path: str = None):
        self._ffmpeg = ffmpeg_path or find_ffmpeg()

    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        ext = Path(rom_path).suffix.lower()

        if ext == '.pbp':
            at3 = self._from_pbp(rom_path)
        elif ext == '.cso':
            at3 = self._from_cso(rom_path)
        else:
            at3 = self._from_iso(rom_path)

        if not at3 or len(at3) < 64:
            return None

        return self._decode_at3(at3)

    # ------------------------------------------------------------------
    # Container readers
    # ------------------------------------------------------------------

    def _from_pbp(self, path: str) -> bytes | None:
        """Read SND0.AT3 from a PBP container."""
        with open(path, 'rb') as f:
            hdr = f.read(0x28)
            if len(hdr) < 0x28 or hdr[:4] != _PBP_MAGIC:
                return None

            offsets = struct.unpack_from('<8I', hdr, 8)
            snd0_off = offsets[_PBP_SND0_IDX]
            snd0_end = offsets[_PBP_SND0_IDX + 1]
            snd0_size = snd0_end - snd0_off

            if snd0_size <= 0:
                return None

            f.seek(snd0_off)
            return f.read(snd0_size)

    def _from_iso(self, path: str) -> bytes | None:
        """Read SND0.AT3 from an ISO9660 UMD image."""
        with open(path, 'rb') as f:
            return self._find_snd0_in_iso(f)

    def _from_cso(self, path: str) -> bytes | None:
        """Read SND0.AT3 from a CISO compressed disc image."""
        import zlib

        with open(path, 'rb') as f:
            hdr = f.read(0x18)
            if len(hdr) < 0x18 or hdr[:4] != b'CISO':
                return None

            _header_size = struct.unpack_from('<I', hdr, 4)[0]
            total_bytes = struct.unpack_from('<Q', hdr, 8)[0]
            block_size = struct.unpack_from('<I', hdr, 16)[0]
            _version = hdr[20]
            align = hdr[21]

            if block_size == 0:
                return None

            total_blocks = (total_bytes + block_size - 1) // block_size

            # Read block index
            f.seek(0x18)
            index_data = f.read((total_blocks + 1) * 4)
            index = struct.unpack_from(f'<{total_blocks + 1}I', index_data, 0)

            class CsoReader:
                """Random-access reader that decompresses CSO blocks."""
                def __init__(self, fobj, index, block_size, align):
                    self._f = fobj
                    self._index = index
                    self._bs = block_size
                    self._align = align
                    self._pos = 0

                def seek(self, pos):
                    self._pos = pos

                def read(self, size):
                    result = bytearray()
                    while size > 0 and self._pos < total_bytes:
                        block_num = self._pos // self._bs
                        block_off = self._pos % self._bs

                        if block_num >= total_blocks:
                            break

                        raw = self._index[block_num]
                        uncompressed = bool(raw & 0x80000000)
                        raw_off = (raw & 0x7FFFFFFF) << self._align
                        next_raw = self._index[block_num + 1]
                        next_off = (next_raw & 0x7FFFFFFF) << self._align
                        chunk_size = next_off - raw_off

                        self._f.seek(raw_off)
                        chunk = self._f.read(chunk_size)

                        if uncompressed:
                            block_data = chunk
                        else:
                            try:
                                block_data = zlib.decompress(chunk, -15)
                            except zlib.error:
                                block_data = chunk

                        available = len(block_data) - block_off
                        take = min(size, available)
                        result.extend(block_data[block_off:block_off + take])
                        self._pos += take
                        size -= take

                    return bytes(result)

            reader = CsoReader(f, index, block_size, align)
            return self._find_snd0_in_iso(reader)

    # ------------------------------------------------------------------
    # ISO9660 SND0.AT3 finder
    # ------------------------------------------------------------------

    def _find_snd0_in_iso(self, f) -> bytes | None:
        """Locate SND0.AT3 in an ISO9660 filesystem.

        Searches for PSP_GAME directory first, then SND0.AT3 within it.
        """
        # Primary Volume Descriptor at sector 16
        f.seek(0x8000)
        pvd = f.read(2048)
        if len(pvd) < 156 + 34 or pvd[1:6] != b'CD001':
            return None

        # Root directory record at PVD + 156
        root_lba = struct.unpack_from('<I', pvd, 156 + 2)[0]
        root_size = struct.unpack_from('<I', pvd, 156 + 10)[0]

        # Read root directory
        f.seek(root_lba * 2048)
        root_dir = f.read(root_size)

        # Find PSP_GAME entry
        psp_game_lba, psp_game_size = self._find_dir_entry(root_dir, b'PSP_GAME')
        if psp_game_lba is None:
            return None

        # Read PSP_GAME directory
        f.seek(psp_game_lba * 2048)
        psp_dir = f.read(psp_game_size)

        # Find SND0.AT3
        snd0_lba, snd0_size = self._find_dir_entry(psp_dir, b'SND0.AT3')
        if snd0_lba is None or snd0_size == 0:
            return None

        f.seek(snd0_lba * 2048)
        return f.read(snd0_size)

    @staticmethod
    def _find_dir_entry(dir_data: bytes, target: bytes):
        """Find an ISO9660 directory entry by name. Returns (LBA, size) or (None, 0)."""
        pos = 0
        while pos < len(dir_data):
            rec_len = dir_data[pos]
            if rec_len == 0:
                # Skip to next sector boundary
                pos = (pos // 2048 + 1) * 2048
                continue
            if pos + rec_len > len(dir_data):
                break

            name_len = dir_data[pos + 32]
            name = dir_data[pos + 33:pos + 33 + name_len]

            # ISO9660 appends ";1" version suffix
            clean = name.split(b';')[0].rstrip(b'.')
            if clean.upper() == target.upper():
                lba = struct.unpack_from('<I', dir_data, pos + 2)[0]
                size = struct.unpack_from('<I', dir_data, pos + 10)[0]
                return lba, size

            pos += rec_len

        return None, 0

    # ------------------------------------------------------------------
    # AT3 -> PCM samples via FFmpeg
    # ------------------------------------------------------------------

    def _decode_at3(self, at3_data: bytes):
        """Decode AT3/RIFF-ATRAC3 to PCM samples using FFmpeg.

        Returns (samples, sample_rate, channels) or None.
        """
        if not self._ffmpeg:
            return None

        tmp_at3 = os.path.join(tempfile.gettempdir(),
                               f'jingles_snd0_{os.getpid()}.at3')
        tmp_wav = os.path.join(tempfile.gettempdir(),
                               f'jingles_snd0_{os.getpid()}.wav')
        try:
            with open(tmp_at3, 'wb') as f:
                f.write(at3_data)

            r = subprocess.run(
                [self._ffmpeg, '-y', '-i', tmp_at3,
                 '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                 tmp_wav],
                capture_output=True, timeout=30,
            )
            if r.returncode != 0 or not os.path.exists(tmp_wav):
                return None

            with open(tmp_wav, 'rb') as f:
                wav_data = f.read()

            # Parse WAV: skip 44-byte header, read s16le samples
            if len(wav_data) <= 44:
                return None

            pcm = wav_data[44:]
            n_samples = len(pcm) // 2
            samples = list(struct.unpack(f'<{n_samples}h', pcm))
            return samples, 44100, 2

        finally:
            for p in (tmp_at3, tmp_wav):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
