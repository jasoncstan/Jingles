"""Wii BNS audio file parser.

BNS (Banner Sound) is a DSP-ADPCM audio container used inside Wii
opening.bnr U8 archives as 'sound.bns' or 'sound.bin'.
All values are big-endian.

Two layout variants exist:
  - Block-interleaved: stereo channels alternate in 0x8000-byte blocks.
    Coefficients are at the offset pointed to by the channel info struct.
  - Contiguous: each channel's data is stored sequentially (ch0 then ch1).
    Coefficients have an 8-byte reference header before the actual data.
"""
import struct
from audio.dsp_adpcm import decode_dsp_adpcm


class BnsParser:
    BNS_MAGIC = b'BNS '

    def parse(self, data: bytes):
        """Parse a BNS file and return (samples, sample_rate, channels).

        Returns None if the data is not a valid BNS file or uses an
        unsupported codec.

        samples is a list of interleaved signed 16-bit integers.
        """
        if len(data) < 0x20 or data[:4] != self.BNS_MAGIC:
            return None

        info_off = struct.unpack_from('>I', data, 0x10)[0]
        data_off = struct.unpack_from('>I', data, 0x18)[0]

        if info_off + 8 > len(data) or data_off + 8 > len(data):
            return None

        info = data[info_off:]
        codec = info[8]
        channels = info[10]
        sample_rate = struct.unpack_from('>H', info, 12)[0]
        total_samples = struct.unpack_from('>I', info, 20)[0]
        ch_list_rel = struct.unpack_from('>I', info, 24)[0]

        # BNS uses codec 0 for DSP-ADPCM (Nintendo SDK convention).
        # Some files may use codec 2 (alternate convention).
        if codec not in (0, 2):
            return None

        if channels < 1 or channels > 2:
            return None

        audio_base = data_off + 8  # skip 'DATA' magic + size
        audio_data = data[audio_base:]
        audio_len = len(audio_data)

        # Parse channel info entries from the INFO block
        ch_params = []
        for c in range(channels):
            entry_base = ch_list_rel + 8 + c * 8
            ch_rel = struct.unpack_from('>I', info, entry_base + 4)[0]
            ch_info = info[ch_rel:]

            adpcm_off = struct.unpack_from('>I', ch_info, 0)[0]

            # Try two coefficient layouts:
            #   1. Coefficients at adpcm_off + 8 (8-byte reference header)
            #   2. Coefficients directly at adpcm_off
            coeffs, hist1, hist2 = self._read_adpcm_params(
                info, adpcm_off)

            ch_params.append((coeffs, hist1, hist2))

        # Determine audio layout and decode
        if channels == 1:
            samples = decode_dsp_adpcm(
                audio_data, ch_params[0][0],
                ch_params[0][1], ch_params[0][2])
            return samples[:total_samples], sample_rate, 1

        # Stereo: try contiguous layout first, then block-interleaved
        result = self._decode_contiguous(
            audio_data, audio_len, ch_params, total_samples)
        if result is None:
            result = self._decode_interleaved(
                audio_data, ch_params, total_samples, channels)

        if result is None:
            return None

        return result, sample_rate, channels

    @staticmethod
    def _read_adpcm_params(info, adpcm_off):
        """Read DSP-ADPCM coefficients and history from INFO block.

        BNS ADPCM info blocks have an 8-byte reference header before
        the actual coefficient data:
          +0x00: 8-byte header (offset/padding)
          +0x08: 16 × s16 coefficients (32 bytes)
          +0x28: s16 pred/scale (ignored)
          +0x2A: s16 hist1
          +0x2C: s16 hist2

        Coefficients always start at adpcm_off + 8.
        """
        coeff_start = adpcm_off + 8

        if coeff_start + 32 + 6 <= len(info):
            coeffs = [struct.unpack_from('>h', info, coeff_start + k * 2)[0]
                      for k in range(16)]
            # State follows coefficients: pred/scale(2) + hist1(2) + hist2(2)
            state_off = coeff_start + 32
            hist1 = struct.unpack_from('>h', info, state_off + 2)[0]
            hist2 = struct.unpack_from('>h', info, state_off + 4)[0]
            return coeffs, hist1, hist2

        return [0] * 16, 0, 0

    @staticmethod
    def _decode_contiguous(audio_data, audio_len, ch_params, total_samples):
        """Decode stereo with contiguous per-channel layout: [ch0][ch1]."""
        half = audio_len // 2
        if half < 8:
            return None

        all_ch = []
        for c, (coeffs, h1, h2) in enumerate(ch_params):
            start = c * half
            ch_audio = audio_data[start:start + half]
            samples = decode_dsp_adpcm(ch_audio, coeffs, h1, h2)
            samples = samples[:total_samples]
            if not samples:
                return None
            all_ch.append(samples)

        length = min(len(s) for s in all_ch)
        if length == 0:
            return None

        merged = []
        for i in range(length):
            for ch_samples in all_ch:
                merged.append(ch_samples[i])
        return merged

    @staticmethod
    def _decode_interleaved(audio_data, ch_params, total_samples, channels):
        """Decode with block-interleaved layout (0x8000-byte blocks)."""
        INTERLEAVE = 0x8000
        all_samples = [[] for _ in range(channels)]

        for c, (coeffs, hist1, hist2) in enumerate(ch_params):
            block_idx = 0
            cur_h1, cur_h2 = hist1, hist2

            while True:
                src_off = block_idx * channels * INTERLEAVE + c * INTERLEAVE
                if src_off >= len(audio_data):
                    break

                block = audio_data[src_off:src_off + INTERLEAVE]
                if not block:
                    break

                new_samples = decode_dsp_adpcm(block, coeffs, cur_h1, cur_h2)
                all_samples[c].extend(new_samples)

                if len(new_samples) >= 2:
                    cur_h1, cur_h2 = new_samples[-1], new_samples[-2]
                elif len(new_samples) == 1:
                    cur_h2, cur_h1 = cur_h1, new_samples[0]

                block_idx += 1

            all_samples[c] = all_samples[c][:total_samples]

        length = min(len(s) for s in all_samples)
        if length == 0:
            return None

        merged = []
        for i in range(length):
            for c in range(channels):
                merged.append(all_samples[c][i])
        return merged
