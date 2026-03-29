"""Wii BNS audio file parser.

BNS (Banner Sound) is a DSP-ADPCM audio container used inside Wii
opening.bnr U8 archives as 'sound.bns'. All values are big-endian.
"""
import struct
from audio.dsp_adpcm import decode_dsp_adpcm


class BnsParser:
    BNS_MAGIC = b'BNS '
    CODEC_DSP_ADPCM = 2

    def parse(self, data: bytes):
        """Parse a BNS file and return (samples, sample_rate, channels).

        Returns None if the data is not a valid BNS file or uses an
        unsupported codec.

        samples is a list of interleaved signed 16-bit integers.
        """
        if len(data) < 0x20 or data[:4] != self.BNS_MAGIC:
            return None

        # BNS file header (big-endian)
        # 0x00: magic 'BNS '
        # 0x04: BOM (0xFEFF)
        # 0x08: file size
        # 0x0C: header size
        # 0x0E: block count (should be 2: INFO + DATA)
        # 0x10: INFO block offset
        # 0x14: INFO block size
        # 0x18: DATA block offset
        # 0x1C: DATA block size

        info_off = struct.unpack_from('>I', data, 0x10)[0]
        data_off = struct.unpack_from('>I', data, 0x18)[0]

        if info_off + 8 > len(data) or data_off + 8 > len(data):
            return None

        # INFO block
        # info+0x00: 'INFO'
        # info+0x08: codec (u8)
        # info+0x09: loop flag (u8)
        # info+0x0A: channel count (u8)
        # info+0x0B: padding
        # info+0x0C: sample rate (u16be)
        # info+0x0E: padding
        # info+0x10: loop start (u32be)  -- frame index
        # info+0x14: total frames (u32be)
        # info+0x18: channel info list offset (u32be, relative to INFO start)

        info = data[info_off:]
        codec = info[8]
        channels = info[10]
        sample_rate = struct.unpack_from('>H', info, 12)[0]
        total_samples = struct.unpack_from('>I', info, 20)[0]
        ch_list_rel = struct.unpack_from('>I', info, 24)[0]

        if codec != self.CODEC_DSP_ADPCM:
            # PCM or other codec – let FFmpeg handle it via generic extractor
            return None

        if channels < 1 or channels > 2:
            return None

        # Channel info list: array of (offset_type u16, pad u16, offset u32)
        # Each offset points to a channel info struct (relative to INFO start)
        ch_data = []
        for c in range(channels):
            entry_base = ch_list_rel + 8 + c * 8  # skip list header
            ch_rel = struct.unpack_from('>I', info, entry_base + 4)[0]
            ch_info = info[ch_rel:]

            # Channel info struct:
            # 0x00: coeff_offset (u32be, relative to INFO start)
            # 0x04: adpcm_state_offset (u32be, relative to INFO start)
            coeff_rel = struct.unpack_from('>I', ch_info, 0)[0]
            state_rel = struct.unpack_from('>I', ch_info, 4)[0]

            # 16 s16be coefficients (8 pairs)
            coeffs = [struct.unpack_from('>h', info, coeff_rel + k * 2)[0]
                      for k in range(16)]

            # Initial ADPCM history values
            hist1 = struct.unpack_from('>h', info, state_rel)[0]
            hist2 = struct.unpack_from('>h', info, state_rel + 2)[0]

            # Channel audio data start is stored per-channel at a fixed offset
            # within the INFO channel entry (offset from DATA block audio start)
            audio_start_rel = struct.unpack_from('>I', ch_info, 8)[0]
            ch_data.append((coeffs, hist1, hist2, audio_start_rel))

        # Decode each channel's DSP-ADPCM data
        # BNS stereo interleaves blocks of INTERLEAVE_SIZE bytes per channel
        INTERLEAVE = 0x8000
        audio_base = data_off + 8  # skip 'DATA' + size (8 bytes)

        all_samples = [[] for _ in range(channels)]

        for c, (coeffs, hist1, hist2, audio_start_rel) in enumerate(ch_data):
            ch_audio = data[audio_base + audio_start_rel:]

            # De-interleave: each channel's data is in INTERLEAVE-byte blocks
            # Layout: [ch0 block][ch1 block][ch0 block][ch1 block]...
            block_idx = 0
            current_h1, current_h2 = hist1, hist2

            while True:
                src_off = block_idx * channels * INTERLEAVE + c * INTERLEAVE
                if src_off >= len(ch_audio):
                    break

                block = ch_audio[src_off:src_off + INTERLEAVE]
                if not block:
                    break

                new_samples = decode_dsp_adpcm(block, coeffs, current_h1, current_h2)
                all_samples[c].extend(new_samples)

                if len(new_samples) >= 2:
                    current_h1, current_h2 = new_samples[-1], new_samples[-2]
                elif len(new_samples) == 1:
                    current_h2, current_h1 = current_h1, new_samples[0]

                block_idx += 1

            # Trim to declared total_samples
            all_samples[c] = all_samples[c][:total_samples]

        # Interleave channels for output
        if channels == 1:
            return all_samples[0], sample_rate, 1

        merged = []
        length = min(len(s) for s in all_samples)
        for i in range(length):
            for c in range(channels):
                merged.append(all_samples[c][i])

        return merged, sample_rate, channels
