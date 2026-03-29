# Jingles

A ROM banner sound extractor that generates short MP3 preview clips from game ROMs. Designed for emulator frontends that need per-game audio jingles.

Jingles scans a ROM directory, extracts or captures banner/title audio from each game, and exports 3-6 second MP3 clips with fade-out, organized by platform.

## Features

- **Native banner extraction** for formats that embed audio:
  - Nintendo 3DS (.3ds, .cci, .cia) — BCWAV from ExeFS banner via CBMD header
  - Nintendo DS (.nds, .dsi) — IMA-ADPCM from DSi-enhanced banners
  - Wii (.wbfs, .wia, .iso) — BNS/DSP-ADPCM from opening.bnr
  - PSP (.iso, .cso, .pbp) — SND0.AT3 from ISO9660 or PBP container
- **RetroArch emulation fallback** for systems without embedded audio (NES, SNES, Game Boy, N64, Genesis, and 50+ other systems) — boots the game headlessly, records title screen audio, strips silence
- **PCSX2 standalone emulation** for PlayStation 2 games — launches PCSX2-Qt with turbo boot, captures audio via WASAPI loopback recording
- **Smart retry** — if emulated audio is silent, retries with longer capture periods and eventually sends Start+A inputs to advance past "Press Start" screens
- **vgmstream** support for hundreds of game audio container formats
- **FFmpeg generic fallback** for any file with an extractable audio stream
- **Filter folder** — optionally limit processing to ROMs matching names in a reference folder or text file (supports MTP devices)
- **Dark-themed tkinter GUI** with progress tracking, per-file status, and log output

## Supported Platforms

| Category | Systems |
|---|---|
| Nintendo | NES, FDS, SNES, Game Boy/Color, GBA, N64, DS, 3DS, Virtual Boy, Pokemon Mini, GameCube, Wii |
| Sega | SG-1000, Master System, Game Gear, Genesis/Mega Drive, 32X |
| NEC | PC Engine/TurboGrafx-16, SuperGrafx |
| Atari | 2600, 5200, 7800, Lynx, Jaguar, ST |
| Sony | PlayStation, PlayStation 2, PSP |
| Other | ColecoVision, Intellivision, Vectrex, WonderSwan/Color, Neo Geo Pocket/Color, Odyssey 2, Fairchild Channel F |
| Computers | Amstrad CPC, MSX, Commodore 64 |
| Chip Music | VGM, SPC, NSF, GBS, GSF, GYM, HES, KSS, PSF, SSF, DSF, SAP, AY |

## Requirements

- **Python 3.11+** (uses only the standard library for core functionality)
- **Windows 10/11** (uses Win32 APIs for headless RetroArch window management and WASAPI loopback)
- **Optional:** `pip install pyaudiowpatch` (only needed for PS2 audio capture via WASAPI loopback)

## External Tools

Place these in a `tools/` directory alongside the project (not included in the repository):

| Tool | Purpose | License | Download |
|---|---|---|---|
| [FFmpeg](https://ffmpeg.org/) | MP3 encoding, AT3 decoding, silence removal, generic audio extraction | LGPL/GPL | [ffmpeg.org/download](https://ffmpeg.org/download.html) |
| [vgmstream](https://github.com/vgmstream/vgmstream) | Decoding hundreds of game audio container formats | ISC | [GitHub Releases](https://github.com/vgmstream/vgmstream/releases) |
| [RetroArch](https://www.retroarch.com/) | Headless emulation for systems without embedded banner audio | GPL-3.0 | [retroarch.com](https://www.retroarch.com/index.php?page=platforms) |
| [PCSX2](https://pcsx2.net/) | PlayStation 2 emulation (standalone, not the RetroArch core) | GPL-3.0 | [GitHub Releases](https://github.com/PCSX2/pcsx2/releases) |

### Tool Setup

```
Jingles/
  tools/
    ffmpeg.exe
    vgmstream-cli.exe
    RetroArch-Win64/
      retroarch.exe
      cores/
        gambatte_libretro.dll
        nestopia_libretro.dll
        snes9x_libretro.dll
        mgba_libretro.dll
        ...
      system/
        disksys.rom              (optional: FDS BIOS)
    PCSX2/                       (optional: PS2 support)
      pcsx2-qt.exe
      bios/
        ps2-0230a-20080220.bin   (USA)
        ps2-0230e-20080220.bin   (EUR)
        ps2-0230j-20080220.bin   (JPN)
```

RetroArch cores can be downloaded from the [libretro buildbot](https://buildbot.libretro.com/nightly/windows/x86_64/latest/). Only cores for systems you want to process are needed.

## Usage

```bash
python jingles.py

# Optional: enable PS2 support
pip install pyaudiowpatch
```

1. Set your ROM folder path
2. Optionally set a filter folder to limit which ROMs are processed
3. Click **Scan ROMs** to discover files
4. Click **Start** to begin extraction

Output MP3s are saved to `output/<Platform>/` with filenames matching the ROM.

## How It Works

Jingles tries multiple extraction methods in order:

1. **Format-specific extractor** — parses the ROM binary directly to extract embedded banner audio (3DS BCWAV, DS IMA-ADPCM, Wii BNS, PSP AT3)
2. **vgmstream** — tries to decode the file as a known game audio format
3. **RetroArch emulation** — boots the game headlessly, records audio for 15-75 seconds, strips leading silence, and clips to 3-6 seconds with fade-out. Retries with longer captures if silent, and sends Start+A inputs as a last resort
4. **PCSX2 emulation** — for PS2 games, launches standalone PCSX2-Qt with turbo fast-forward, sends Start to advance past menus, and captures title audio via WASAPI loopback recording
5. **FFmpeg generic** — attempts to extract any audio stream from the file

## Output Format

- 44.1 kHz stereo MP3 at 128 kbps
- 3-6 seconds duration with 1-second fade-out
- Named after the ROM file stem
- Organized by platform: `output/Nintendo 3DS/`, `output/PlayStation 2/`, etc.

## BIOS Files

Some systems require BIOS files for emulation:

| System | File | Location |
|---|---|---|
| Famicom Disk System | `disksys.rom` | `tools/RetroArch-Win64/system/` |
| PlayStation (USA) | `scph5501.bin` | `tools/RetroArch-Win64/system/` |
| PlayStation (JPN) | `scph5500.bin` | `tools/RetroArch-Win64/system/` |
| PlayStation (EUR) | `scph5502.bin` | `tools/RetroArch-Win64/system/` |
| PlayStation 2 (USA) | `ps2-0230a-20080220.bin` | `tools/PCSX2/bios/` |
| PlayStation 2 (EUR) | `ps2-0230e-20080220.bin` | `tools/PCSX2/bios/` |
| PlayStation 2 (JPN) | `ps2-0230j-20080220.bin` | `tools/PCSX2/bios/` |

Jingles will log a warning if a required BIOS is missing when processing ROMs for that system.

## License

This project is licensed under the [MIT License](LICENSE).

### Third-Party Tool Licenses

Jingles does not bundle or redistribute any third-party tools. The following tools are used at runtime if provided by the user:

- **FFmpeg** — Licensed under [LGPL 2.1+](https://www.ffmpeg.org/legal.html) or GPL depending on build configuration. Copyright (c) the FFmpeg developers.
- **vgmstream** — Licensed under the [ISC License](https://github.com/vgmstream/vgmstream/blob/master/COPYING). Copyright (c) the vgmstream contributors.
- **RetroArch** — Licensed under [GPL-3.0](https://github.com/libretro/RetroArch/blob/master/COPYING). Copyright (c) the libretro team. Individual cores have their own licenses.
- **PCSX2** — Licensed under [GPL-3.0](https://github.com/PCSX2/pcsx2/blob/master/COPYING.GPLv3). Copyright (c) the PCSX2 team.

