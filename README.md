# Jingles

A ROM banner sound extractor that generates MP3 preview clips from game ROMs. Designed for emulator frontends that need per-game audio jingles.

Jingles scans a ROM directory, extracts or captures banner/title audio from each game, and exports MP3 clips organized by platform. Native banner extractions preserve the original audio in full; emulation-based captures are clipped to 3–6 seconds with fade-out.

## Features

- **Native banner extraction** for formats that embed audio (full-length, no trim/fade):
  - Nintendo 3DS (.3ds, .cci, .cia) — BCWAV from ExeFS banner via CBMD header
  - Nintendo DS (.nds, .dsi) — IMA-ADPCM from DSi-enhanced banners
  - Wii (.wbfs, .wia, .rvz, .iso) — BNS/DSP-ADPCM from opening.bnr. Supports both decrypted dumps and encrypted retail discs (encrypted discs require DolphinTool)
  - Wii U — bootSound.btsnd (48kHz DSP-ADPCM/PCM) extracted from decrypted game folders (code/content/meta/ structure). Encrypted WUX/WUD disc images are not supported; decrypt with CDecrypt or similar first
  - PSP (.iso, .cso, .pbp) — SND0.AT3 from ISO9660 or PBP container
- **RetroArch emulation fallback** for systems without embedded audio (NES, SNES, Game Boy, N64, Genesis, and 50+ other systems) — boots the game headlessly, records title screen audio, strips silence
- **PCSX2 standalone emulation** for PlayStation 2 games — launches PCSX2-Qt with turbo boot, captures audio via WASAPI loopback recording
- **Smart retry** — if emulated audio is silent, retries with longer capture periods and eventually sends Start+A inputs to advance past "Press Start" screens
- **vgmstream** support for hundreds of game audio container formats
- **FFmpeg generic fallback** for any file with an extractable audio stream
- **Filter folder** — optionally limit processing to ROMs matching names in a reference folder or text file (supports MTP devices)
- **ADB device support** — scan and pull ROMs directly from an Android handheld (e.g., Ayn Thor, Odin, Retroid) over USB, with optional push-back of generated MP3s to the device
- **Configurable settings** — adjust clip durations, fade times, MP3 bitrate, RetroArch capture frames, PS2 emulation timing, and more from a Settings dialog (no restart needed)
- **Game-specific rules** — override settings per ROM via filename patterns scoped to specific platforms. Includes a curated library of pre-built rules for Pokemon, Final Fantasy, Mega Man, Castlevania, Sonic, Mario, Zelda, and more
- **Right-click ROM actions** — create, edit, or delete a rule directly from any scanned ROM in the file list, with platform and pattern auto-detected (works inside .zip/.7z archives)
- **Tool status dashboard** — at-a-glance Required/Optional indicators in the top bar; click to see each tool's path or get a download link to the official source
- **Dark-themed tkinter GUI** with progress tracking, per-file status, and log output

## Supported Platforms

| Category | Systems |
|---|---|
| Nintendo | NES, FDS, SNES, Game Boy/Color, GBA, N64, DS, 3DS, Virtual Boy, Pokemon Mini, GameCube, Wii, Wii U |
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
| [DolphinTool](https://dolphin-emu.org/) | Extracting banner audio from encrypted/compressed Wii disc images (RVZ, WIA, encrypted ISO/WBFS) | GPL-2.0 | [dolphin-emu.org](https://dolphin-emu.org/download/) |
| [ADB (Android Debug Bridge)](https://developer.android.com/tools/adb) | Pull ROMs from / push MP3s to Android devices over USB | Apache 2.0 | [SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools#downloads) |

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
    Dolphin/                     (optional: encrypted/compressed Wii discs)
      DolphinTool.exe
    platform-tools/              (optional: ADB device support)
      adb.exe
      AdbWinApi.dll
      AdbWinUsbApi.dll
```

RetroArch cores can be downloaded from the [libretro buildbot](https://buildbot.libretro.com/nightly/windows/x86_64/latest/). Only cores for systems you want to process are needed.

### DolphinTool (Optional — for encrypted/compressed Wii discs)

DolphinTool is only needed if your Wii games are in encrypted or compressed formats (RVZ, WIA, or encrypted retail ISO/WBFS). Decrypted WBFS and ISO files work without it.

DolphinTool ships with [Dolphin Emulator](https://dolphin-emu.org/download/). Download Dolphin and copy `DolphinTool.exe` into `tools/Dolphin/`. Jingles will also find it if Dolphin is in your system PATH.

### Wii U Games

Wii U banner audio (`bootSound.btsnd`) can only be extracted from **decrypted game folders** — the directory structure used by Cemu and other Wii U emulators:

```
Game Name/
  code/
  content/
  meta/
    bootSound.btsnd    ← banner audio (auto-detected by Jingles)
    meta.xml
```

Point Jingles at a folder containing one or more decrypted Wii U game folders. The scanner will auto-detect them and display each game with the folder name and "Wii U" platform.

**Encrypted WUX/WUD disc images cannot be read directly.** Use a tool like [CDecrypt](https://github.com/VitaSmith/cdecrypt) with the game's title key to produce the decrypted folder structure first.

### ADB Setup (Optional — for pulling ROMs directly from a device)

ADB is only needed if you want to pull ROMs directly from an Android handheld (Ayn Thor, Odin, Retroid Pocket, etc.) over USB without manually copying them to your PC first. If you already have your ROMs on a local or network drive, you can skip this section entirely.

ADB lets Jingles browse your device's storage, pull selected ROMs for processing, and optionally push the generated MP3s back to the device.

#### 1. Install ADB

Download the **SDK Platform-Tools** zip from Google:
https://developer.android.com/tools/releases/platform-tools#downloads

Extract it and either:
- Place `adb.exe` (and its companion files `AdbWinApi.dll`, `AdbWinUsbApi.dll`) into the `tools/` directory alongside Jingles, **or**
- Extract the `platform-tools/` folder into `tools/` so the layout is `tools/platform-tools/adb.exe`, **or**
- Add the extracted folder to your system PATH

Jingles will auto-detect ADB in any of these locations.

#### 2. Enable Developer Mode on Your Device

1. Open **Settings** on your Android device
2. Go to **About phone** (or **About device** / **System → About**)
3. Find **Build number** and tap it **7 times** — you will see a toast message saying "You are now a developer!"
4. Go back to **Settings → System → Developer options** (the location varies by device; on some devices it appears directly in Settings)

#### 3. Enable USB Debugging

1. In **Developer options**, find **USB debugging** and toggle it **on**
2. Connect the device to your PC via USB
3. On the device, a prompt will appear: **"Allow USB debugging?"** — tap **Allow** (check "Always allow from this computer" to avoid future prompts)
4. If prompted for a USB connection mode on the device, select **File Transfer (MTP)** — this does not affect ADB but ensures the device stays awake

#### 4. Verify the Connection

Open a terminal and run:
```bash
adb devices
```
You should see your device listed (e.g., `571e6154  device`). If it shows `unauthorized`, check the device screen for the USB debugging authorization prompt.

#### 5. Using ADB in Jingles

1. Launch Jingles and switch the **Source** to **ADB Device**
2. Select your device from the dropdown (click **Refresh** if it doesn't appear)
3. Click **Browse…** to navigate the device filesystem — shortcut buttons for Internal storage, SD Card, and ROM folders are auto-detected
4. Click **Scan ROMs** to discover ROMs on the device
5. Click **Start** — Jingles will pull the selected ROMs to a local cache, extract audio, and generate MP3s
6. Optionally check **Push MP3s to device** and set a target folder to copy the generated jingles back to the device

Pulled ROMs are cached locally in `adb_cache/` so re-runs skip files that haven't changed on the device.

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

## Configuration

The top bar exposes four configuration entry points:

| Button | What it does |
|---|---|
| **Settings…** | Edit global defaults: clip duration, fade times, MP3 bitrate/sample rate, RetroArch capture frames, PS2 emulation timing |
| **Rules…** | Manage game-specific rules that override global settings for matching ROMs |
| **BIOS…** | Manage BIOS file paths for systems that need them |
| **Required: X/Y** / **Optional: X/Y** | Click either indicator to open the External Tools dialog showing each tool's status, path, and a download link |

### Settings

Open via the **Settings…** button. All values are persisted in `jingles_config.json` and take effect on the next file processed (no restart needed).

| Group | Setting | Default | Notes |
|---|---|---|---|
| Output | Max clip duration (s) | 6.0 | Length of emulation-captured clips |
| Output | Min clip duration (s) | 3.0 | Minimum length before fade is applied |
| Output | Fade-out duration (s) | 1.0 | End fade for emulation clips |
| Output | Fade-in duration (s) | 0.03 | Short fade-in to avoid pops |
| Output | MP3 bitrate | 128k | e.g. 128k, 192k, 256k |
| Output | MP3 sample rate (Hz) | 44100 | Output sample rate |
| RetroArch | Capture frames | 900 | Default emulation frames to record (~15 s at 60 fps) |
| RetroArch | Max retry multiplier | 3 | Longest retry is this many times the default |
| PS2 | Turbo boot duration (s) | 3 | Time PCSX2 stays in turbo to skip logos |
| PS2 | Settle duration (s) | 2 | Wait at normal speed before recording |
| PS2 | Record duration (s) | 8 | Length of audio capture |

Banner extractions (3DS, DS, Wii, Wii U, PSP) ignore the clip duration / fade settings — they always preserve the full original audio. Only emulation-based and fallback paths are clipped.

### Game-Specific Rules

Open via the **Rules…** button. A rule overrides any global setting when its pattern matches a ROM's filename and the ROM is on one of the rule's selected platforms.

Each rule has:

- **Name** — descriptive label
- **Pattern** — substring or regex matched against the ROM filename (case-insensitive)
- **Platforms** — empty list = any platform, otherwise the rule only fires on the listed platforms
- **Overrides** — checkboxes for each setting you want to override

Rules are checked in the order they appear; the **first match wins**, so put more specific rules above more general ones.

#### Right-click on a ROM

Right-click any ROM in the scan list to:

- **Create new rule from this ROM…** — opens the rule editor with name, pattern, and platform pre-filled. For ROMs inside `.zip`/`.7z` archives, the inner extension is detected so the platform pre-selects correctly.
- **Edit rule: {name}** / **Delete rule: {name}** — shown when an existing rule already matches this ROM, so you can quickly tweak or remove it.

#### Pre-built rule libraries

The [`rules/`](rules/) folder ships with curated JSON files for series that need different settings due to long publisher logos or intros:

| File | Description |
|---|---|
| [`rules/game_freak.json`](rules/game_freak.json) | Pokemon series across all platforms (Game Boy → 3DS) |
| [`rules/final_fantasy.json`](rules/final_fantasy.json) | Final Fantasy and other Square Enix RPGs (Chrono, Kingdom Hearts, Dragon Quest, NieR) |
| [`rules/long_intros.json`](rules/long_intros.json) | Mega Man, Castlevania, Metal Gear, Sonic, Zelda, Mario, Kirby, Metroid, EarthBound, Fire Emblem, Resident Evil, and others |

To use them: open **Rules… → Import…**, pick a file, and choose **Yes (Merge)** to add the rules without overwriting your existing ones. Duplicates are auto-renamed with numeric suffixes so nothing is lost.

You can also export your own rules via **Rules… → Export…** to share with other users.

## How It Works

Jingles tries multiple extraction methods in order:

1. **Format-specific extractor** — parses the ROM binary directly to extract embedded banner audio (3DS BCWAV, DS IMA-ADPCM, Wii BNS, Wii U BTSND, PSP AT3). Output preserves the original audio in full — no trimming or fade effects. For encrypted Wii discs (RVZ, WIA, encrypted ISO/WBFS), DolphinTool is used to extract the banner data.
2. **vgmstream** — tries to decode the file as a known game audio format
3. **RetroArch emulation** — boots the game headlessly, records audio for 15–75 seconds, strips leading silence, and clips to 3–6 seconds with fade-out. Retries with longer captures if silent, and sends Start+A inputs as a last resort
4. **PCSX2 emulation** — for PS2 games, launches standalone PCSX2-Qt with turbo fast-forward, sends Start to advance past menus, and captures title audio via WASAPI loopback recording
5. **FFmpeg generic** — attempts to extract any audio stream from the file

## Output Format

- 44.1 kHz stereo MP3 at 128 kbps
- Banner extractions: full original duration, no effects applied
- Emulation/fallback extractions: 3–6 seconds with 1-second fade-out
- Named after the ROM file stem (Wii U games use the game folder name)
- Organized by platform: `output/Nintendo 3DS/`, `output/Wii U/`, etc.

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
- **Dolphin Emulator / DolphinTool** — Licensed under [GPL-2.0](https://github.com/dolphin-emu/dolphin/blob/master/COPYING). Copyright (c) the Dolphin Emulator team.
- **ADB (Android Debug Bridge)** — Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). Copyright (c) Google LLC.

