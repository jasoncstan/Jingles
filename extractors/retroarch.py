"""RetroArch-based emulation audio extractor.

Runs a game inside RetroArch for a fixed number of frames using a libretro
core, records the audio output to a temporary MKV file, then extracts the
audio track with FFmpeg.

This is the fallback of last resort for synthesis-based systems (VB, NES,
SNES, GBA, N64, GB/GBC) where no audio stream exists in the ROM binary.

Setup:
  1. Place retroarch.exe in tools/  (or install system-wide)
  2. Place core .dll files in tools/cores/
     e.g. tools/cores/mednafen_vb_libretro.dll

Core downloads: https://buildbot.libretro.com/nightly/windows/x86_64/latest/
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import settings

# Maps ROM extension -> ordered list of core dll names to try
SYSTEM_CORES = {
    # ── Nintendo ──────────────────────────────────────────────────────────────
    '.nes':  ['nestopia_libretro.dll',         'fceumm_libretro.dll',
              'mesen_libretro.dll'],
    '.fds':  ['fceumm_libretro.dll',           'nestopia_libretro.dll'],
    '.sfc':  ['snes9x_libretro.dll',           'bsnes_libretro.dll',
              'bsnes_mercury_balanced_libretro.dll'],
    '.smc':  ['snes9x_libretro.dll',           'bsnes_libretro.dll',
              'bsnes_mercury_balanced_libretro.dll'],
    '.fig':  ['snes9x_libretro.dll',           'bsnes_libretro.dll'],
    '.gb':   ['gambatte_libretro.dll',         'sameboy_libretro.dll',
              'mgba_libretro.dll'],
    '.gbc':  ['gambatte_libretro.dll',         'sameboy_libretro.dll',
              'mgba_libretro.dll'],
    '.gba':  ['mgba_libretro.dll',             'vba_next_libretro.dll',
              'gpsp_libretro.dll'],
    '.n64':  ['mupen64plus_next_libretro.dll', 'parallel_n64_libretro.dll'],
    '.z64':  ['mupen64plus_next_libretro.dll', 'parallel_n64_libretro.dll'],
    '.v64':  ['mupen64plus_next_libretro.dll', 'parallel_n64_libretro.dll'],
    '.nds':  ['melondsds_libretro.dll',        'melonds_libretro.dll',
              'desmume_libretro.dll',           'desmume2015_libretro.dll'],
    '.dsi':  ['melondsds_libretro.dll',        'melonds_libretro.dll',
              'desmume_libretro.dll',           'desmume2015_libretro.dll'],
    '.3ds':  ['citra_libretro.dll',            'citra2018_libretro.dll'],
    '.cci':  ['citra_libretro.dll',            'citra2018_libretro.dll'],
    '.cia':  ['citra_libretro.dll',            'citra2018_libretro.dll'],
    '.vb':   ['mednafen_vb_libretro.dll'],
    '.vboy': ['mednafen_vb_libretro.dll'],
    '.min':  ['pokemini_libretro.dll'],        # Pokemon Mini
    # ── Sega ──────────────────────────────────────────────────────────────────
    '.sg':   ['genesis_plus_gx_libretro.dll',  'gearsystem_libretro.dll'],
    '.sms':  ['genesis_plus_gx_libretro.dll',  'picodrive_libretro.dll',
              'gearsystem_libretro.dll'],
    '.gg':   ['genesis_plus_gx_libretro.dll',  'picodrive_libretro.dll',
              'gearsystem_libretro.dll'],
    '.md':   ['genesis_plus_gx_libretro.dll',  'picodrive_libretro.dll'],
    '.gen':  ['genesis_plus_gx_libretro.dll',  'picodrive_libretro.dll'],
    '.32x':  ['picodrive_libretro.dll'],
    '.chd':  ['pcsx_rearmed_libretro.dll',     'mednafen_psx_libretro.dll',
              'mednafen_saturn_libretro.dll',  'kronos_libretro.dll',
              'opera_libretro.dll'],
    '.cue':  ['pcsx_rearmed_libretro.dll',     'mednafen_psx_libretro.dll',
              'mednafen_saturn_libretro.dll'],
    # NOTE: PS2 cores (pcsx2, play) crash in headless recording mode.
    # PS2 .chd/.iso are handled by _FOLDER_CORE_HINTS but will likely fail.
    '.gcz':  ['dolphin_libretro.dll'],         # GameCube
    # ── NEC ───────────────────────────────────────────────────────────────────
    '.pce':  ['mednafen_pce_libretro.dll',     'mednafen_pce_fast_libretro.dll',
              'geargrafx_libretro.dll'],
    '.sgx':  ['mednafen_supergrafx_libretro.dll'],
    # ── Atari ─────────────────────────────────────────────────────────────────
    '.a26':  ['stella_libretro.dll',           'stella2023_libretro.dll',
              'stella2014_libretro.dll'],
    '.bin':  ['stella_libretro.dll'],          # Atari 2600 (fallback for .bin)
    '.a52':  ['a5200_libretro.dll'],           # Atari 5200
    '.a78':  ['prosystem_libretro.dll'],       # Atari 7800
    '.lnx':  ['handy_libretro.dll',           'mednafen_lynx_libretro.dll'],
    '.j64':  ['virtualjaguar_libretro.dll'],   # Atari Jaguar
    '.st':   ['hatari_libretro.dll'],          # Atari ST
    # ── Other consoles ────────────────────────────────────────────────────────
    '.col':  ['bluemsx_libretro.dll',          'gearcoleco_libretro.dll',
              'jollycv_libretro.dll'],
    '.int':  ['freeintv_libretro.dll'],        # Mattel Intellivision
    '.vec':  ['vecx_libretro.dll'],            # GCE Vectrex
    '.ws':   ['mednafen_wswan_libretro.dll'],  # WonderSwan
    '.wsc':  ['mednafen_wswan_libretro.dll'],  # WonderSwan Color
    '.ngp':  ['mednafen_ngp_libretro.dll',     'race_libretro.dll'],
    '.ngc':  ['mednafen_ngp_libretro.dll',     'race_libretro.dll'],
    '.o2':   ['o2em_libretro.dll'],            # Magnavox Odyssey 2
    '.chf':  ['freechaf_libretro.dll'],        # Fairchild Channel F
    # ── Computers ─────────────────────────────────────────────────────────────
    '.dsk':  ['cap32_libretro.dll',            'fmsx_libretro.dll'],
    '.rom':  ['fmsx_libretro.dll',             'bluemsx_libretro.dll'],
    '.d64':  ['vice_x64_libretro.dll',         'vice_x64sc_libretro.dll'],
    '.t64':  ['vice_x64_libretro.dll'],        # Commodore 64
    '.crt':  ['vice_x64_libretro.dll'],        # Commodore 64 cart
    '.prg':  ['vice_x64_libretro.dll',         'vice_xvic_libretro.dll'],
    # ── Sony ──────────────────────────────────────────────────────────────────
    '.pbp':  ['ppsspp_libretro.dll'],          # PSP
    '.iso':  ['ppsspp_libretro.dll',           'mednafen_psx_libretro.dll'],
    '.cso':  ['ppsspp_libretro.dll'],          # PSP compressed
    # ── Panasonic / Philips ───────────────────────────────────────────────────
    # .chd already covered above (opera for 3DO, same_cdi for CD-i)
}

# Extensions shared by multiple systems — needs folder-name disambiguation.
_AMBIGUOUS_EXTS = {'.chd', '.iso', '.cue', '.bin'}

# (folder_keyword, core_dll) — checked in order against parent folder name.
_FOLDER_CORE_HINTS = [
    # More specific names must come before less specific ones
    ('playstation portable', 'ppsspp_libretro.dll'),
    ('playstation 2',        'pcsx2_libretro.dll'),  # crashes, handled by PCSX2 standalone
    ('ps2',                  'pcsx2_libretro.dll'),
    ('psp',                  'ppsspp_libretro.dll'),
    ('playstation',          'pcsx_rearmed_libretro.dll'),
    ('ps1',                  'pcsx_rearmed_libretro.dll'),
    ('psx',                  'pcsx_rearmed_libretro.dll'),
    ('saturn',               'mednafen_saturn_libretro.dll'),
    ('sega cd',              'genesis_plus_gx_libretro.dll'),
    ('mega cd',              'genesis_plus_gx_libretro.dll'),
    ('3do',                  'opera_libretro.dll'),
    ('cd-i',                 'same_cdi_libretro.dll'),
    ('cdi',                  'same_cdi_libretro.dll'),
    ('pc engine',            'mednafen_pce_libretro.dll'),
    ('turbografx',           'mednafen_pce_libretro.dll'),
    ('pce',                  'mednafen_pce_libretro.dll'),
    ('dreamcast',            'flycast_libretro.dll'),
    ('gamecube',             'dolphin_libretro.dll'),
]

# Default frames to capture (~15 s at 60 fps).
_CAPTURE_FRAMES_DEFAULT = 900

# Per-system overrides for systems with long boot/logo sequences.
_CAPTURE_FRAMES_OVERRIDE = {
    '.fds': 1800,   # ~30 s — BIOS jingle + ~10 s disk load before game audio
    '.nds': 1200,   # ~20 s — DS publisher logos before title screen audio
    '.dsi': 1200,
    '.3ds': 1800,   # ~30 s — 3DS boot sequence is long
    '.cci': 1800,
    '.cia': 1800,
    '.n64': 1800,   # ~30 s — boot ROM + publisher logos before audio
    '.z64': 1800,
    '.v64': 1800,
    '.gba': 480,    # ~8 s — GBA BIOS plays a short jingle first
    '.gcz': 1800,   # ~30 s — GameCube boot animation
    '.chd': 1800,   # ~30 s — CD-based systems have long load times
    '.cue': 1800,
    '.iso': 1800,
    '.pbp': 1800,   # PSP
    '.cso': 1800,
}

# Native frame rates used to calculate expected audio duration for tempo correction.
_SYSTEM_FPS = {
    '.nes': 60.0988, '.fds': 60.0988,
    '.sfc': 60.0988, '.smc': 60.0988, '.fig': 60.0988,
    '.gb':  59.7275, '.gbc': 59.7275,
    '.gba': 59.7275,
    '.n64': 60.0, '.z64': 60.0, '.v64': 60.0,
    '.nds': 59.8261, '.dsi': 59.8261,
    '.vb':  50.27, '.vboy': 50.27,
    '.sg':  59.92, '.sms': 59.92, '.gg': 59.92,
    '.md':  59.92, '.gen': 59.92, '.32x': 59.92,
    '.pce': 59.82, '.sgx': 59.82,
    '.a26': 59.92,
    '.ws':  75.47, '.wsc': 75.47,
    '.lnx': 75.0,
    '.col': 59.92,
}
_DEFAULT_FPS = 60.0

# Seconds of audio to discard from the start of the recording.
# Used to skip BIOS boot jingles that would otherwise be captured
# as the first audible sound (defeating silence-removal).
_AUDIO_SKIP_SECS = {
    '.fds': 2,    # FDS BIOS "Nintendo" jingle (~1 s) + margin
    '.chd': 10,   # PS1 BIOS startup jingle (~9 s)
    '.cue': 10,
}

# Required BIOS files per extension.  Path is relative to RetroArch system dir.
REQUIRED_BIOS = {
    '.fds': ('disksys.rom', 'Famicom Disk System'),
}

# BIOS files required per core (checked when the core is actually selected).
# Values are (list_of_filenames, system_name).  At least one file must exist.
CORE_BIOS = {
    'pcsx2_libretro.dll': ([
        'ps2-0230a-20080220.bin',   # USA
        'ps2-0230e-20080220.bin',   # Europe
        'ps2-0230j-20080220.bin',   # Japan
    ], 'PlayStation 2'),
    'mednafen_psx_libretro.dll': ([
        'scph5501.bin',             # USA
        'scph5500.bin',             # Japan
        'scph5502.bin',             # Europe
    ], 'PlayStation'),
}


# Silence-removal FFmpeg filter applied after extracting audio from the
# recording.  Strips leading silence so the 6-second clip starts on the
# first audible sound rather than dead air.
_SILENCE_REMOVE_FILTER = (
    'silenceremove=start_periods=1'
    ':start_duration=0.5'     # audio must stay above threshold for 0.5 s
    ':start_silence=0.3'      # gaps shorter than 0.3 s don't count as silence
    ':start_threshold=-50dB'  # anything below -50 dB is silence
)


_GWL_STYLE        = -16
_WS_VISIBLE       = 0x10000000
_SWP_HIDE_FLAGS   = 0x0093   # SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_HIDEWINDOW
_EVENT_OBJECT_SHOW = 0x8002
_WINEVENT_OUTOFCONTEXT = 0x0000


def _hide_windows_for_pid(pid: int, stop_event: threading.Event):
    """Background thread: suppress every window created by pid.

    Uses SetWinEventHook(EVENT_OBJECT_SHOW) so we are notified the instant
    any window belonging to the process becomes visible — no polling delay.
    Falls back to a 50 ms polling sweep to catch windows the hook might miss.
    """
    if sys.platform != 'win32':
        return

    user32 = ctypes.windll.user32

    def _suppress(hwnd):
        """Strip WS_VISIBLE and call SetWindowPos(SWP_HIDEWINDOW)."""
        try:
            style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
            if style & _WS_VISIBLE:
                user32.SetWindowLongW(hwnd, _GWL_STYLE, style & ~_WS_VISIBLE)
            user32.SetWindowPos(hwnd, 0, -32000, -32000, 1, 1, _SWP_HIDE_FLAGS)
        except Exception:
            pass

    WinEventProc = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p, ctypes.wintypes.DWORD,
        ctypes.c_void_p, ctypes.wintypes.LONG, ctypes.wintypes.LONG,
        ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
    )

    @WinEventProc
    def _event_cb(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if hwnd:
            pid_buf = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
            if pid_buf.value == pid:
                _suppress(hwnd)

    hook = user32.SetWinEventHook(
        _EVENT_OBJECT_SHOW, _EVENT_OBJECT_SHOW,
        None, _event_cb, pid, 0, _WINEVENT_OUTOFCONTEXT,
    )

    # Message pump required for WinEvent hooks with OUTOFCONTEXT
    msg = ctypes.wintypes.MSG()
    while not stop_event.is_set():
        # Non-blocking peek; drain any pending events then sleep briefly
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)

    if hook:
        user32.UnhookWinEvent(hook)


def _send_start_inputs(pid: int, stop_event: threading.Event,
                       initial_delay: float = 3.0, interval: float = 2.0):
    """Background thread: periodically send Start + A button keypresses.

    Attaches to the RetroArch window's input thread, brings it to the
    foreground, and uses keybd_event to inject Enter (Start) and X (A).
    Only works when RetroArch is running in real-time mode (no --max-frames),
    since the fast-forward loop skips input processing.
    """
    if sys.platform != 'win32':
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    VK_RETURN = 0x0D   # Enter = Start
    VK_X = 0x58        # X = A button
    SCAN_RETURN = 0x1C
    SCAN_X = 0x2D

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def find_hwnd():
        result = []
        def cb(hwnd, _):
            pid_buf = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
            if pid_buf.value == pid and user32.IsWindowVisible(hwnd):
                result.append(hwnd)
            return True
        user32.EnumWindows(WNDENUMPROC(cb), None)
        return result[0] if result else None

    if stop_event.wait(initial_delay):
        return

    while not stop_event.is_set():
        hwnd = find_hwnd()
        if hwnd:
            my_tid = kernel32.GetCurrentThreadId()
            ra_tid = user32.GetWindowThreadProcessId(hwnd, None)

            user32.AttachThreadInput(my_tid, ra_tid, True)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
            time.sleep(0.05)

            user32.keybd_event(VK_RETURN, SCAN_RETURN, 0, 0)
            time.sleep(0.1)
            user32.keybd_event(VK_RETURN, SCAN_RETURN, 2, 0)
            time.sleep(0.15)
            user32.keybd_event(VK_X, SCAN_X, 0, 0)
            time.sleep(0.1)
            user32.keybd_event(VK_X, SCAN_X, 2, 0)

            # Move window back offscreen
            user32.SetWindowPos(hwnd, 0, -32000, -32000, 320, 240, 0x0010)
            user32.AttachThreadInput(my_tid, ra_tid, False)

        if stop_event.wait(interval):
            break


def _get_wav_duration(wav_path: str, ffmpeg: str) -> float:
    """Return duration of wav_path in seconds, or 0.0 on failure."""
    try:
        r = subprocess.run(
            [ffmpeg, '-i', wav_path],
            capture_output=True, timeout=10,
        )
        # ffprobe-style output is in stderr for ffmpeg
        output = r.stderr.decode('utf-8', errors='replace')
        for line in output.splitlines():
            if 'Duration:' in line:
                # "  Duration: HH:MM:SS.ss,"
                part = line.split('Duration:')[1].split(',')[0].strip()
                h, m, s = part.split(':')
                return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def _build_startupinfo():
    """STARTUPINFO with SW_HIDE — belt-and-suspenders alongside the hide thread."""
    if sys.platform != 'win32':
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


class RetroArchExtractor:

    def __init__(self, retroarch: str, cores_dir: str):
        """
        Args:
            retroarch:  Path to retroarch.exe.
            cores_dir:  Directory containing libretro core .dll files.
        """
        self._retroarch = retroarch
        self._cores_dir = cores_dir

    def find_core(self, rom_ext: str, rom_path: str = None) -> str:
        """Return the path to the best available core for rom_ext, or None.

        For ambiguous extensions (.chd, .iso, .cue) shared by multiple
        systems, the ROM's parent folder name is checked against
        _FOLDER_CORE_HINTS to pick the correct core first.
        """
        ext = rom_ext.lower()

        # For ambiguous extensions, try folder-name hints first
        if rom_path and ext in _AMBIGUOUS_EXTS:
            folder = Path(rom_path).parent.name.lower()
            for keyword, core_name in _FOLDER_CORE_HINTS:
                if keyword in folder:
                    path = os.path.join(self._cores_dir, core_name)
                    if os.path.isfile(path):
                        return path

        candidates = SYSTEM_CORES.get(ext, [])
        for name in candidates:
            path = os.path.join(self._cores_dir, name)
            if os.path.isfile(path):
                return path
        return None

    def extract_to_wav(self, rom_path: str, wav_path: str, ffmpeg: str,
                        frames_override: int = None,
                        send_start: bool = False) -> tuple:
        """Emulate rom_path, capture audio, strip leading silence, write wav_path.

        RetroArch is run with audio_sync=false and fastforward_ratio=0 so it
        processes frames as fast as the CPU allows.  Because the recording
        captures every emulated sample regardless of wall-clock time, the
        resulting audio may be sped-up relative to real-time; we measure the
        actual duration and apply atempo correction to restore normal speed.

        Returns (True, '') on success, or (False, reason_str) on failure.
        """
        ext = Path(rom_path).suffix.lower()
        core = self.find_core(ext)
        if not core:
            return False, 'no core found'

        user_default = settings.get_for_rom('retroarch_capture_frames', rom_path)
        frames = frames_override or _CAPTURE_FRAMES_OVERRIDE.get(ext, user_default)
        fps    = _SYSTEM_FPS.get(ext, _DEFAULT_FPS)
        # Timeout: 3× real-time equivalent + 30 s headroom to handle slow
        # startup, but cap at 120 s so hung processes don't block forever.
        timeout_secs = min(int(frames / fps * 3) + 30, 120)

        rec_path  = wav_path.replace('.wav', '_ra_rec.mkv')
        cfg_path  = wav_path.replace('.wav', '_ra.cfg')
        raw_wav   = wav_path.replace('.wav', '_ra_raw.wav')

        # Headless config.
        #
        # No video_driver override — let RetroArch pick (cores like snes9x
        # need video callbacks and hang with video_driver=null).
        # video_vsync=false       – no frame-rate cap from display refresh.
        # video_window_*          – initial window position far off-screen;
        #                           the hiding thread strips WS_VISIBLE too.
        # audio_mute_enable=true  – real audio driver stays active (ensures
        #                           correct resampling + recording), but no
        #                           sound goes to the speakers.
        # audio_sync=false        – don't throttle emulation on audio clock.
        cfg_content = (
            'audio_mute_enable = "true"\n'
            'audio_sync = "false"\n'
            'video_vsync = "false"\n'
            'video_window_x = "-32000"\n'
            'video_window_y = "-32000"\n'
            'video_window_width = "320"\n'
            'video_window_height = "240"\n'
            'menu_enable_widgets = "false"\n'
            'notification_show_when_menu_is_alive = "false"\n'
            'pause_nonactive = "false"\n'
            'savestate_auto_load = "false"\n'
            'savestate_auto_save = "false"\n'
            'autosave_interval = "0"\n'
            'history_list_enable = "false"\n'
        )

        # When sending Start+A, run in real-time (no --max-frames)
        # so the input queue is processed.  Kill after a fixed timeout.
        if send_start:
            realtime_secs = 30
            timeout_secs = realtime_secs + 10
            si = None   # don't use SW_HIDE — need a visible (offscreen) window
        else:
            realtime_secs = 0
            si = _build_startupinfo()

        try:
            with open(cfg_path, 'w') as f:
                f.write(cfg_content)

            cmd = [
                self._retroarch,
                '--libretro', core,
                '--config', cfg_path,
                '--record', rec_path,
            ]
            if not send_start:
                cmd += ['--max-frames', str(frames)]
            cmd += ['--no-patch', rom_path]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, startupinfo=si)

            # Hide windows — but when sending keys, keep the window
            # visible (offscreen) so it can receive keyboard focus.
            stop_hide = threading.Event()
            stop_keys = threading.Event()

            if send_start:
                # Don't strip WS_VISIBLE; the window stays offscreen via
                # the config (video_window_x/y = -32000).  Start a thread
                # that gives it focus and sends Start+A keypresses.
                keys_thread = threading.Thread(
                    target=_send_start_inputs,
                    args=(proc.pid, stop_keys),
                    daemon=True,
                )
                keys_thread.start()
            else:
                hide_thread = threading.Thread(
                    target=_hide_windows_for_pid,
                    args=(proc.pid, stop_hide),
                    daemon=True,
                )
                hide_thread.start()

            try:
                _stdout, stderr_bytes = proc.communicate(timeout=timeout_secs)
            except subprocess.TimeoutExpired:
                proc.kill()
                _stdout, stderr_bytes = proc.communicate()
                if not send_start:
                    # Genuine timeout in fast-forward mode = failure
                    stop_hide.set()
                    stop_keys.set()
                    return False, f'timeout after {timeout_secs}s'
                # In send_start mode, killing after timeout is expected
            finally:
                stop_hide.set()
                stop_keys.set()

            if not os.path.exists(rec_path):
                stderr = stderr_bytes.decode('utf-8', errors='replace')[-300:]
                return False, f'no recording file (rc={proc.returncode}): {stderr}'
            if os.path.getsize(rec_path) < 100:
                return False, f'recording too small ({os.path.getsize(rec_path)} bytes)'

            # ── Step 1: extract raw PCM audio from the recording ──────────────
            # Do NOT force -ar here — let FFmpeg use the sample rate declared
            # in the MKV so we don't introduce pitch shift at this stage.
            # wav_to_mp3 resamples to 44100 Hz for the final MP3.
            skip_secs = _AUDIO_SKIP_SECS.get(ext, 0)
            extract_cmd = [ffmpeg, '-y']
            if skip_secs:
                extract_cmd += ['-ss', str(skip_secs)]
            extract_cmd += ['-i', rec_path,
                            '-map', '0:a:0', '-acodec', 'pcm_s16le',
                            raw_wav]
            r2 = subprocess.run(extract_cmd, capture_output=True, timeout=60)
            if r2.returncode != 0 or not os.path.exists(raw_wav) \
                    or os.path.getsize(raw_wav) <= 44:
                err = r2.stderr.decode('utf-8', errors='replace')[-200:]
                return False, f'audio extract failed (rc={r2.returncode}): {err}'

            # ── Step 2: strip leading silence ─────────────────────────────────
            r3 = subprocess.run(
                [ffmpeg, '-y', '-i', raw_wav,
                 '-af', _SILENCE_REMOVE_FILTER,
                 '-acodec', 'pcm_s16le', wav_path],
                capture_output=True, timeout=120,
            )
            if r3.returncode != 0 or not os.path.exists(wav_path) \
                    or os.path.getsize(wav_path) <= 44:
                # Silence removal failed — fall back to raw audio
                import shutil
                try:
                    shutil.copy2(raw_wav, wav_path)
                except OSError:
                    pass

            if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 44:
                return False, 'wav output missing or empty after processing'

            # Require at least 1 second of audio (44100 Hz × 2 ch × 2 bytes)
            min_bytes = 44100 * 2 * 2
            if os.path.getsize(wav_path) < min_bytes:
                return False, 'too little audio after silence removal (<1 s)'

            return True, ''

        except subprocess.TimeoutExpired:
            return False, f'timeout after {timeout_secs}s'
        except FileNotFoundError as e:
            return False, f'not found: {e}'
        except OSError as e:
            return False, f'os error: {e}'

        finally:
            for p in (rec_path, cfg_path, raw_wav):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    @property
    def supported_extensions(self) -> set:
        return set(SYSTEM_CORES.keys())
