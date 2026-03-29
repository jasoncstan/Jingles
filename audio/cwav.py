"""Nintendo 3DS CWAV (BCWAV) audio file parser.

CWAV is the audio format embedded in 3DS banner files. All values are
little-endian. The file may appear wrapped inside a CBMD/BCMA container;
find_and_parse() scans for the CWAV magic automatically.
"""
import struct
from audio.ima_adpcm import decode_ima_adpcm
from audio.dsp_adpcm import decode_dsp_adpcm


class CwavParser:
    CWAV_MAGIC = b'CWAV'

    # Encoding type codes
    ENC_PCM8 = 0
    ENC_PCM16 = 1
    ENC_DSP_ADPCM = 2
    ENC_IMA_ADPCM = 3

    def find_and_parse(self, banner_data: bytes):
        """Locate and parse CWAV audio from a 3DS banner (CBMD container).

        Tries the CBMD header pointer at +0x84 first, then falls back to
        scanning for the CWAV magic.

        Returns (interleaved_s16_samples, sample_rate, channel_count)
        or None if no valid CWAV is found.
        """
        # Primary: CBMD header stores the CWAV offset at +0x84
        if len(banner_data) >= 0x88 and banner_data[:4] == b'CBMD':
            cwav_off = struct.unpack_from('<I', banner_data, 0x84)[0]
            if (cwav_off and cwav_off + 4 <= len(banner_data)
                    and banner_data[cwav_off:cwav_off + 4] == self.CWAV_MAGIC):
                result = self._parse(banner_data, cwav_off)
                if result is not None:
                    return result

        # Fallback: try at offset 0
        if banner_data[:4] == self.CWAV_MAGIC:
            result = self._parse(banner_data, 0)
            if result is not None:
                return result

        # Fallback: scan for CWAV magic at any 4-byte aligned position
        for off in range(4, len(banner_data) - 4, 4):
            if banner_data[off:off + 4] == self.CWAV_MAGIC:
                result = self._parse(banner_data, off)
                if result is not None:
                    return result

        return None

    def _parse(self, data: bytes, base: int):
        """Parse a CWAV file starting at byte offset base within data."""
        if base + 0x20 > len(data):
            return None

        # CWAV header (little-endian):
        # +0x00: 'CWAV'
        # +0x04: BOM (0xFEFF = LE)
        # +0x06: header size
        # +0x08: version
        # +0x0C: file size
        # +0x10: block count
        # +0x12: padding
        # +0x14: block references (block_count * 12 bytes each)
        #         ref = type(u16) + pad(u16) + offset(u32, from FILE base)

        block_count = struct.unpack_from('<H', data, base + 0x10)[0]
        if block_count < 2:
            return None

        info_off = None
        audio_off = None

        for b in range(block_count):
            ref_base = base + 0x14 + b * 12
            if ref_base + 8 > len(data):
                break
            ref_type = struct.unpack_from('<H', data, ref_base)[0]
            ref_off = struct.unpack_from('<I', data, ref_base + 4)[0]

            if ref_type == 0x7000:    # INFO block
                info_off = base + ref_off
            elif ref_type == 0x7001:  # DATA block
                audio_off = base + ref_off

        if info_off is None or audio_off is None:
            return None

        # INFO block layout (offsets from info_off):
        # +0x00: 'INFO' magic
        # +0x04: block size
        # +0x08: encoding (u8)
        # +0x09: loop flag (u8)
        # +0x0A: padding (u16)
        # +0x0C: sample rate (u32)
        # +0x10: loop start sample (u32)
        # +0x14: loop end / total samples (u32)
        # +0x18: padding (u32)
        # +0x1C: channel info count (u32)
        # +0x20: channel info references (8 bytes each)
        #        ref offsets are relative to info_off + 0x1C

        encoding = data[info_off + 8]
        sample_rate = struct.unpack_from('<I', data, info_off + 0x0C)[0]
        total_samples = struct.unpack_from('<I', data, info_off + 0x14)[0]

        # Channel count lives at +0x1C in the INFO block
        if info_off + 0x20 > len(data):
            return None
        channel_count = struct.unpack_from('<I', data, info_off + 0x1C)[0]

        if channel_count < 1 or channel_count > 2 or total_samples == 0:
            return None

        # Reference offset base for channel info pointers
        ref_base_off = info_off + 0x1C

        # DATA block audio starts 8 bytes after DATA magic
        audio_data_base = audio_off + 8

        if encoding == self.ENC_PCM16:
            n = total_samples * channel_count
            if audio_data_base + n * 2 > len(data):
                n = (len(data) - audio_data_base) // 2
            samples = list(struct.unpack_from(f'<{n}h', data, audio_data_base))
            return samples, sample_rate, channel_count

        elif encoding in (self.ENC_IMA_ADPCM, self.ENC_DSP_ADPCM):
            ch_samples = []
            for c in range(channel_count):
                # Channel references start at info_off + 0x20, each 8 bytes
                ch_ref_pos = info_off + 0x20 + c * 8
                if ch_ref_pos + 8 > len(data):
                    return None
                ch_info_rel = struct.unpack_from('<I', data, ch_ref_pos + 4)[0]
                # Channel info offsets are relative to ref_base_off (info_off + 0x1C)
                ch_info_off = ref_base_off + ch_info_rel

                if ch_info_off + 16 > len(data):
                    return None

                # Channel info:
                # +0x00: sample data ref (type u16, pad u16, offset u32 from DATA audio base)
                # +0x08: ADPCM info ref (type u16, pad u16, offset u32 from ref_base_off)
                ch_audio_rel = struct.unpack_from('<I', data, ch_info_off + 4)[0]
                ch_audio = data[audio_data_base + ch_audio_rel:]

                if encoding == self.ENC_IMA_ADPCM:
                    ch_samples.append(decode_ima_adpcm(ch_audio)[:total_samples])
                else:
                    # DSP-ADPCM: ADPCM info reference at ch_info_off + 0x08
                    # Offset is relative to the channel info structure itself
                    adpcm_ref_rel = struct.unpack_from('<I', data, ch_info_off + 12)[0]
                    adpcm_off = ch_info_off + adpcm_ref_rel
                    coeffs = [struct.unpack_from('<h', data, adpcm_off + k * 2)[0]
                               for k in range(16)]
                    # +0x20: predictor/scale (u16, skip)
                    # +0x22: yn1 / hist1 (s16)
                    # +0x24: yn2 / hist2 (s16)
                    hist1 = struct.unpack_from('<h', data, adpcm_off + 34)[0]
                    hist2 = struct.unpack_from('<h', data, adpcm_off + 36)[0]
                    ch_samples.append(
                        decode_dsp_adpcm(ch_audio, coeffs, hist1, hist2)[:total_samples]
                    )

            # Interleave channels
            if channel_count == 1:
                return ch_samples[0], sample_rate, 1

            merged = []
            length = min(len(s) for s in ch_samples)
            for i in range(length):
                for c in range(channel_count):
                    merged.append(ch_samples[c][i])
            return merged, sample_rate, channel_count

        return None  # PCM8 or unrecognised encoding
