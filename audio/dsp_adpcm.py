"""Nintendo DSP-ADPCM decoder used by GameCube/Wii audio (BNS format)."""


def decode_dsp_adpcm(data: bytes, coeffs: list, hist1: int = 0, hist2: int = 0) -> list:
    """Decode Nintendo DSP-ADPCM data to a list of signed 16-bit PCM samples.

    Args:
        data:   Raw ADPCM bytes. Frames are 8 bytes each:
                  1 header byte (high nibble=scale_exp, low nibble=coeff_index)
                  7 data bytes (14 nibbles, HIGH nibble first per byte)
        coeffs: List of 16 signed integers (8 pairs c1,c2 for each predictor index).
                Stored as 1.11 fixed-point; the decode formula divides by 2048.
        hist1:  Initial previous sample (yn-1), default 0.
        hist2:  Initial sample before that (yn-2), default 0.

    Returns a list of int values in range [-32768, 32767].
    """
    samples = []
    pos = 0
    length = len(data)

    while pos + 7 < length:
        header = data[pos]
        pos += 1

        scale_shift = header & 0x0F
        coeff_index = (header >> 4) & 0x07
        c1 = coeffs[coeff_index * 2]
        c2 = coeffs[coeff_index * 2 + 1]

        for _ in range(7):
            if pos >= length:
                break
            byte = data[pos]
            pos += 1

            # High nibble first for DSP-ADPCM (opposite of NDS IMA-ADPCM)
            for nibble in ((byte >> 4) & 0x0F, byte & 0x0F):
                # Sign-extend 4-bit value
                nibble_signed = nibble if nibble < 8 else nibble - 16

                # DSP-ADPCM decode formula (GCN SDK spec):
                # sample = (nibble_signed << scale_shift) * 2048 + c1*hist1 + c2*hist2 + 1024) >> 11
                val = ((nibble_signed << (scale_shift + 11)) + c1 * hist1 + c2 * hist2 + 1024) >> 11
                val = max(-32768, min(32767, val))

                samples.append(val)
                hist2 = hist1
                hist1 = val

    return samples
