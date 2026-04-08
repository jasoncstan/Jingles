"""Jingles main application window (tkinter)."""
import os
import queue
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from scanner import scan_directory
from utils import (find_ffmpeg, find_7z, find_vgmstream, find_retroarch,
                   find_dolphintool, get_platform, safe_stem, game_stem,
                   SUPPORTED_EXTENSIONS, load_config, save_config,
                   OUTPUT_BASE, get_mp3_path, PLATFORM_NAMES)
from worker import ProcessingWorker
from adb import (find_adb, list_devices, list_directory, scan_device_roms,
                 pull_file, push_file, AdbRomCache)

# ── Colour palette ────────────────────────────────────────────────────────────
BG       = '#1E1E2E'
BG_PANEL = '#181825'
BG_ENTRY = '#2A2A3D'
FG       = '#CDD6F4'
FG_DIM   = '#6C7086'
ACCENT   = '#89B4FA'
SUCCESS  = '#A6E3A1'
WARNING  = '#F9E2AF'
ERROR    = '#F38BA8'
PROGRESS = '#89DCEB'


class JinglesApp(tk.Tk):
    POLL_MS = 50

    def __init__(self):
        super().__init__()
        self.title('Jingles – ROM Banner Sound Extractor')
        self.geometry('1000x680')
        self.minsize(760, 500)
        self.configure(bg=BG)

        self._ffmpeg              = find_ffmpeg()
        self._7z                  = find_7z()
        self._vgmstream           = find_vgmstream()
        self._retroarch, self._retroarch_cores = find_retroarch()
        self._dolphintool          = find_dolphintool()
        self._adb                 = find_adb()
        self._worker: ProcessingWorker = None
        self._msg_queue           = queue.Queue()
        self._rom_paths: list     = []

        self._input_var     = tk.StringVar()
        self._filter_var    = tk.StringVar()
        self._status_var    = tk.StringVar(value='Ready')
        self._recursive_var = tk.BooleanVar(value=True)
        self._count_var     = tk.StringVar(value='No ROMs loaded')

        # ADB state
        self._source_mode       = tk.StringVar(value='local')
        self._adb_serial        = tk.StringVar()
        self._adb_remote_dir    = tk.StringVar()
        self._adb_push_var      = tk.BooleanVar(value=False)
        self._adb_push_dir      = tk.StringVar()
        self._adb_remote_paths  = []     # parallel to _rom_paths in ADB mode
        self._adb_cache: AdbRomCache = None
        self._adb_pull_thread   = None
        self._adb_push_thread   = None

        # Restore last directories
        cfg = load_config()
        if cfg.get('last_input_dir'):
            self._input_var.set(cfg['last_input_dir'])
        if cfg.get('last_filter_dir'):
            self._filter_var.set(cfg['last_filter_dir'])
        if cfg.get('last_source_mode'):
            self._source_mode.set(cfg['last_source_mode'])
        if cfg.get('last_adb_serial'):
            self._adb_serial.set(cfg['last_adb_serial'])
        if cfg.get('last_adb_remote_dir'):
            self._adb_remote_dir.set(cfg['last_adb_remote_dir'])
        if cfg.get('last_adb_push_dir'):
            self._adb_push_dir.set(cfg['last_adb_push_dir'])

        self._build_ui()
        self._apply_styles()
        self._poll_queue()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        top = tk.Frame(self, bg=BG_PANEL, pady=8)
        top.pack(fill='x')

        tk.Label(top, text='🎵  Jingles', font=('Segoe UI', 18, 'bold'),
                 bg=BG_PANEL, fg=ACCENT).pack(side='left', padx=16)

        # Tool status summary indicators (clickable)
        self._optional_lbl = tk.Label(
            top, font=('Segoe UI', 9, 'underline'),
            bg=BG_PANEL, cursor='hand2')
        self._optional_lbl.pack(side='right', padx=(0, 16))
        self._optional_lbl.bind('<Button-1>',
                                lambda e: self._open_tools_status())

        self._required_lbl = tk.Label(
            top, font=('Segoe UI', 9, 'underline'),
            bg=BG_PANEL, cursor='hand2')
        self._required_lbl.pack(side='right', padx=(0, 8))
        self._required_lbl.bind('<Button-1>',
                                lambda e: self._open_tools_status())

        tk.Button(top, text='BIOS…', command=self._open_bios_manager,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(0, 8))
        tk.Button(top, text='Rules…', command=self._open_rules_manager,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(0, 8))
        tk.Button(top, text='Settings…', command=self._open_settings,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(0, 8))
        self._refresh_tool_labels()

        # ── Settings row ─────────────────────────────────────────────────────
        cfg_frame = tk.Frame(self, bg=BG, padx=12, pady=8)
        cfg_frame.pack(fill='x')

        # Source selector row
        src_row = tk.Frame(cfg_frame, bg=BG)
        src_row.grid(row=0, column=0, columnspan=3, sticky='w', pady=3)
        tk.Label(src_row, text='Source:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e'
                 ).pack(side='left', padx=(0, 6))
        tk.Radiobutton(src_row, text='Local Folder', variable=self._source_mode,
                       value='local', bg=BG, fg=FG, selectcolor=BG_ENTRY,
                       activebackground=BG, activeforeground=FG,
                       font=('Segoe UI', 10),
                       command=self._on_source_changed
                       ).pack(side='left', padx=(0, 12))
        tk.Radiobutton(src_row, text='ADB Device', variable=self._source_mode,
                       value='adb', bg=BG, fg=FG, selectcolor=BG_ENTRY,
                       activebackground=BG, activeforeground=FG,
                       font=('Segoe UI', 10),
                       command=self._on_source_changed
                       ).pack(side='left')

        # --- Local folder widgets (row 1) ---
        self._local_lbl = tk.Label(cfg_frame, text='ROM Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e')
        self._local_lbl.grid(row=1, column=0, sticky='e', padx=(0, 6), pady=3)
        self._local_entry = tk.Entry(cfg_frame, textvariable=self._input_var,
                 bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 10))
        self._local_entry.grid(row=1, column=1, sticky='ew', pady=3)
        self._local_browse = tk.Button(cfg_frame, text='Browse…',
                  command=self._browse_input,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D')
        self._local_browse.grid(row=1, column=2, padx=(6, 0), pady=3)

        # --- ADB device widgets (row 1, hidden by default) ---
        self._adb_dev_lbl = tk.Label(cfg_frame, text='Device:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e')
        self._adb_dev_display = tk.StringVar()  # display label, not serial
        self._adb_dev_combo = ttk.Combobox(cfg_frame,
                 textvariable=self._adb_dev_display,
                 state='readonly', font=('Segoe UI', 10))
        self._adb_dev_btns = tk.Frame(cfg_frame, bg=BG)
        tk.Button(self._adb_dev_btns, text='Refresh',
                  command=self._refresh_adb_devices,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left')

        # ADB remote folder (row 2 in ADB mode)
        self._adb_dir_lbl = tk.Label(cfg_frame, text='Device Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e')
        self._adb_dir_entry = tk.Entry(cfg_frame,
                 textvariable=self._adb_remote_dir, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 10))
        self._adb_dir_btns = tk.Frame(cfg_frame, bg=BG)
        tk.Button(self._adb_dir_btns, text='Browse…',
                  command=self._browse_device_folder,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left')

        # ADB push-back row (row 3 in ADB mode)
        self._adb_push_frame = tk.Frame(cfg_frame, bg=BG)
        ttk.Checkbutton(self._adb_push_frame, text='Push MP3s to device:',
                        variable=self._adb_push_var,
                        style='Jingles.TCheckbutton').pack(side='left')
        tk.Entry(self._adb_push_frame, textvariable=self._adb_push_dir,
                 bg=BG_ENTRY, fg=FG, insertbackground=FG, relief='flat',
                 font=('Segoe UI', 9), width=40
                 ).pack(side='left', padx=(6, 0), fill='x', expand=True)
        tk.Button(self._adb_push_frame, text='Browse…',
                  command=self._browse_device_push_folder,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left', padx=(4, 0))

        # Filter folder (optional — limits scan to matching names)
        tk.Label(cfg_frame, text='Filter Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e'
                 ).grid(row=5, column=0, sticky='e', padx=(0, 6), pady=3)
        tk.Entry(cfg_frame, textvariable=self._filter_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 10)
                 ).grid(row=5, column=1, sticky='ew', pady=3)
        filter_btns = tk.Frame(cfg_frame, bg=BG)
        filter_btns.grid(row=5, column=2, padx=(6, 0), pady=3)
        tk.Button(filter_btns, text='Browse…', command=self._browse_filter,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left')
        tk.Button(filter_btns, text='✕', command=lambda: self._filter_var.set(''),
                  bg=BG_ENTRY, fg=FG_DIM, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), width=2, activebackground='#3A3A5D'
                  ).pack(side='left', padx=(2, 0))

        # Output folder (read-only label + Open button)
        tk.Label(cfg_frame, text='Output Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e'
                 ).grid(row=6, column=0, sticky='e', padx=(0, 6), pady=3)
        tk.Label(cfg_frame, text=OUTPUT_BASE, bg=BG_ENTRY, fg=FG_DIM,
                 font=('Segoe UI', 9), anchor='w', relief='flat'
                 ).grid(row=6, column=1, sticky='ew', pady=3, ipady=4, ipadx=4)
        tk.Button(cfg_frame, text='Open…', command=self._open_output,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).grid(row=6, column=2, padx=(6, 0), pady=3)

        # Options row
        opt_row = tk.Frame(cfg_frame, bg=BG)
        opt_row.grid(row=7, column=0, columnspan=3, sticky='w', pady=2)
        ttk.Checkbutton(opt_row, text='Scan subfolders',
                        variable=self._recursive_var,
                        style='Jingles.TCheckbutton').pack(side='left')
        tk.Label(opt_row, textvariable=self._count_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(side='left', padx=16)

        cfg_frame.columnconfigure(1, weight=1)

        # Show/hide based on initial source mode
        self._on_source_changed()

        # ── Action buttons ───────────────────────────────────────────────────
        btn_bar = tk.Frame(self, bg=BG, padx=12, pady=4)
        btn_bar.pack(fill='x')

        self._scan_btn = tk.Button(
            btn_bar, text='Scan ROMs', width=12, command=self._on_scan,
            bg=ACCENT, fg=BG, font=('Segoe UI', 10, 'bold'),
            relief='flat', cursor='hand2', activebackground='#74A8F0')
        self._scan_btn.pack(side='left', padx=(0, 8))

        self._start_btn = tk.Button(
            btn_bar, text='Start', width=10, command=self._on_start,
            bg=SUCCESS, fg=BG, font=('Segoe UI', 10, 'bold'),
            relief='flat', cursor='hand2', state='disabled',
            activebackground='#8DC98A')
        self._start_btn.pack(side='left', padx=(0, 8))

        self._stop_btn = tk.Button(
            btn_bar, text='Stop', width=10, command=self._on_stop,
            bg=ERROR, fg=BG, font=('Segoe UI', 10, 'bold'),
            relief='flat', cursor='hand2', state='disabled',
            activebackground='#CC7090')
        self._stop_btn.pack(side='left')

        # Selection buttons (right side of button bar)
        tk.Button(btn_bar, text='Select All', width=10,
                  command=self._select_all,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(4, 0))
        tk.Button(btn_bar, text='Deselect All', width=10,
                  command=self._deselect_all,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(4, 0))

        # ── Search bar ────────────────────────────────────────────────────────
        search_frame = tk.Frame(self, bg=BG, padx=12, pady=2)
        search_frame.pack(fill='x')
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', lambda *_: self._on_search())
        tk.Label(search_frame, text='Search:', bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 9)).pack(side='left')
        tk.Entry(search_frame, textvariable=self._search_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 9),
                 width=30).pack(side='left', padx=(4, 8))
        tk.Button(search_frame, text='Select Matches', width=14,
                  command=lambda: self._select_matches(True),
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left', padx=(0, 4))
        tk.Button(search_frame, text='Deselect Matches', width=14,
                  command=lambda: self._select_matches(False),
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left')
        self._match_count_var = tk.StringVar()
        tk.Label(search_frame, textvariable=self._match_count_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(side='left', padx=8)

        # ── File list ─────────────────────────────────────────────────────────
        list_frame = tk.Frame(self, bg=BG, padx=12)
        list_frame.pack(fill='both', expand=True)

        cols = ('sel', 'name', 'platform', 'status')
        self._tree = ttk.Treeview(list_frame, columns=cols, show='headings',
                                  selectmode='browse', style='Jingles.Treeview')
        self._tree.heading('sel',      text='')
        self._tree.heading('name',     text='ROM Name')
        self._tree.heading('platform', text='Platform')
        self._tree.heading('status',   text='Status')
        self._tree.column('sel',      width=30,  stretch=False, anchor='center')
        self._tree.column('name',     width=470, stretch=True)
        self._tree.column('platform', width=150, stretch=False, anchor='center')
        self._tree.column('status',   width=140, stretch=False, anchor='center')

        # Toggle selection on click
        self._tree.bind('<ButtonRelease-1>', self._on_tree_click)
        self._tree.bind('<Button-3>', self._on_tree_right_click)

        vsb = ttk.Scrollbar(list_frame, orient='vertical',   command=self._tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient='horizontal', command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self._tree.tag_configure('done',    foreground=SUCCESS)
        self._tree.tag_configure('exists',  foreground=FG_DIM)
        self._tree.tag_configure('error',   foreground=ERROR)
        self._tree.tag_configure('noaudio', foreground=WARNING)
        self._tree.tag_configure('proc',    foreground=ACCENT)
        self._tree.tag_configure('pending', foreground=FG_DIM)
        self._tree.tag_configure('highlight', background='#3A3A5D')

        # ── Progress bar ─────────────────────────────────────────────────────
        prog_frame = tk.Frame(self, bg=BG, padx=12, pady=4)
        prog_frame.pack(fill='x')
        self._progress = ttk.Progressbar(prog_frame, mode='determinate',
                                         style='Jingles.Horizontal.TProgressbar')
        self._progress.pack(fill='x', side='left', expand=True)
        tk.Label(prog_frame, textvariable=self._status_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9),
                 width=30, anchor='e').pack(side='right', padx=(8, 0))

        # ── Log panel ─────────────────────────────────────────────────────────
        log_outer = tk.Frame(self, bg=BG, padx=12)
        log_outer.pack(fill='x')
        tk.Label(log_outer, text='Log', bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 8)).pack(anchor='w')
        log_frame = tk.Frame(log_outer, bg=BG_PANEL)
        log_frame.pack(fill='x')
        self._log = tk.Text(log_frame, height=6, bg=BG_PANEL, fg=FG,
                            font=('Consolas', 8), relief='flat',
                            state='disabled', wrap='none')
        log_sb = ttk.Scrollbar(log_frame, orient='vertical', command=self._log.yview)
        self._log.configure(yscrollcommand=log_sb.set)
        self._log.pack(side='left', fill='x', expand=True)
        log_sb.pack(side='right', fill='y')

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Jingles.Treeview',
                        background=BG_PANEL, fieldbackground=BG_PANEL,
                        foreground=FG, rowheight=22, font=('Segoe UI', 9))
        style.configure('Jingles.Treeview.Heading',
                        background=BG_ENTRY, foreground=ACCENT,
                        font=('Segoe UI', 9, 'bold'), relief='flat')
        style.map('Jingles.Treeview',
                  background=[('selected', '#313155')],
                  foreground=[('selected', FG)])
        style.configure('Jingles.Horizontal.TProgressbar',
                        troughcolor=BG_PANEL, background=PROGRESS, borderwidth=0)
        style.configure('Jingles.TCheckbutton', background=BG, foreground=FG,
                        font=('Segoe UI', 9))
        style.map('Jingles.TCheckbutton', background=[('active', BG)])

    # ── Tool status labels ────────────────────────────────────────────────────

    def _tool_list(self):
        """Return a list of (name, required, path, description, url) tuples."""
        return [
            ('FFmpeg', True, self._ffmpeg,
             'MP3 encoding and audio conversion. Required for all output.',
             'https://ffmpeg.org/download.html'),
            ('7-Zip', False, self._7z,
             'Extracts .7z archives. Without it, only .zip archives work.',
             'https://www.7-zip.org/download.html'),
            ('vgmstream', False, self._vgmstream,
             'Decodes hundreds of game audio container formats.',
             'https://github.com/vgmstream/vgmstream/releases'),
            ('RetroArch', False, self._retroarch,
             'Headless emulation fallback for systems without embedded '
             'banner audio (NES, SNES, GBA, etc.).',
             'https://www.retroarch.com/index.php?page=platforms'),
            ('DolphinTool', False, self._dolphintool,
             'Extracts banner audio from encrypted/compressed Wii disc '
             'images (RVZ, WIA, encrypted ISO/WBFS).',
             'https://dolphin-emu.org/download/'),
            ('ADB', False, self._adb,
             'Pulls ROMs from / pushes MP3s to Android devices over USB.',
             'https://developer.android.com/tools/releases/platform-tools#downloads'),
        ]

    def _refresh_tool_labels(self):
        tools = self._tool_list()
        required = [t for t in tools if t[1]]
        optional = [t for t in tools if not t[1]]

        req_found = sum(1 for t in required if t[2])
        opt_found = sum(1 for t in optional if t[2])

        self._required_lbl.config(
            text=f'Required: {req_found}/{len(required)}',
            fg=SUCCESS if req_found == len(required) else ERROR)
        self._optional_lbl.config(
            text=f'Optional: {opt_found}/{len(optional)}',
            fg=SUCCESS if opt_found == len(optional)
            else (WARNING if opt_found > 0 else FG_DIM))

    def _open_tools_status(self):
        """Open a dialog showing per-tool status, paths, and download links."""
        import webbrowser

        dlg = tk.Toplevel(self)
        dlg.title('External Tools')
        dlg.geometry('720x560')
        dlg.minsize(640, 460)
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text='External Tools',
                 font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(dlg,
                 text='Place tools in the tools/ directory or install them '
                      'system-wide. Required tools must be present for '
                      'Jingles to function. Optional tools enable extra '
                      'features and fallbacks.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9),
                 wraplength=680, justify='left'
                 ).pack(anchor='w', padx=16)

        tools = self._tool_list()
        required = [t for t in tools if t[1]]
        optional = [t for t in tools if not t[1]]

        # Bottom buttons
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(side='bottom', fill='x', padx=16, pady=(8, 12))
        tk.Button(btn_frame, text='Refresh',
                  command=lambda: (self._rescan_tools(),
                                   dlg.destroy(),
                                   self._open_tools_status()),
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10),
                  activebackground='#3A3A5D'
                  ).pack(side='left')
        tk.Button(btn_frame, text='Close', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10),
                  activebackground='#3A3A5D'
                  ).pack(side='right')

        # Scrollable content
        outer = tk.Frame(dlg, bg=BG)
        outer.pack(fill='both', expand=True, padx=16, pady=4)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind(
            '<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        def _add_tool_row(tool):
            name, is_required, path, desc, url = tool
            row = tk.Frame(inner, bg=BG_PANEL)
            row.pack(fill='x', pady=4, padx=2)

            # Status icon + name line
            top_line = tk.Frame(row, bg=BG_PANEL)
            top_line.pack(fill='x', padx=8, pady=(6, 2))

            status_text = '✓' if path else '✗'
            status_color = SUCCESS if path else (ERROR if is_required else WARNING)
            tk.Label(top_line, text=status_text,
                     bg=BG_PANEL, fg=status_color,
                     font=('Segoe UI', 12, 'bold')
                     ).pack(side='left', padx=(0, 8))
            tk.Label(top_line, text=name,
                     bg=BG_PANEL, fg=FG,
                     font=('Segoe UI', 11, 'bold')
                     ).pack(side='left')

            # Download link button (always shown, opens browser to the
            # official download page).  When the tool is missing it's
            # shown in the accent color to highlight the action.
            def _download(u=url):
                try:
                    webbrowser.open(u)
                except Exception:
                    pass

            if path:
                tk.Button(top_line, text='Download…',
                          command=_download,
                          bg=BG_ENTRY, fg=ACCENT, relief='flat',
                          cursor='hand2', font=('Segoe UI', 8),
                          activebackground='#3A3A5D'
                          ).pack(side='right', padx=2)
            else:
                tk.Button(top_line, text='Download…',
                          command=_download,
                          bg=ACCENT, fg=BG, relief='flat',
                          cursor='hand2',
                          font=('Segoe UI', 8, 'bold'),
                          activebackground='#74A8F0'
                          ).pack(side='right', padx=2)

            # Description
            tk.Label(row, text=desc,
                     bg=BG_PANEL, fg=FG_DIM, font=('Segoe UI', 9),
                     wraplength=640, justify='left', anchor='w'
                     ).pack(fill='x', padx=8, pady=(0, 2))

            # Path or download URL
            if path:
                tk.Label(row, text=path,
                         bg=BG_PANEL, fg=ACCENT,
                         font=('Consolas', 8),
                         wraplength=640, justify='left', anchor='w'
                         ).pack(fill='x', padx=8, pady=(0, 6))
            else:
                tk.Label(row, text=f'Not installed — {url}',
                         bg=BG_PANEL, fg=FG_DIM,
                         font=('Consolas', 8),
                         wraplength=640, justify='left', anchor='w'
                         ).pack(fill='x', padx=8, pady=(0, 6))

        # Required section
        req_found = sum(1 for t in required if t[2])
        tk.Label(inner,
                 text=f'Required ({req_found}/{len(required)})',
                 font=('Segoe UI', 11, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', pady=(8, 4))
        for tool in required:
            _add_tool_row(tool)

        # Optional section
        opt_found = sum(1 for t in optional if t[2])
        tk.Label(inner,
                 text=f'Optional ({opt_found}/{len(optional)})',
                 font=('Segoe UI', 11, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', pady=(12, 4))
        for tool in optional:
            _add_tool_row(tool)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        dlg.bind('<Destroy>',
                 lambda e: canvas.unbind_all('<MouseWheel>')
                 if e.widget == dlg else None)

    def _rescan_tools(self):
        """Re-detect external tools (called from the tools status dialog)."""
        self._ffmpeg = find_ffmpeg()
        self._7z = find_7z()
        self._vgmstream = find_vgmstream()
        self._retroarch, self._retroarch_cores = find_retroarch()
        self._dolphintool = find_dolphintool()
        self._adb = find_adb()
        self._refresh_tool_labels()

    # ── Source mode switching ─────────────────────────────────────────────────

    def _on_source_changed(self):
        """Show/hide widgets based on the selected source mode."""
        mode = self._source_mode.get()
        if mode == 'local':
            # Show local widgets
            self._local_lbl.grid(row=1, column=0, sticky='e', padx=(0, 6), pady=3)
            self._local_entry.grid(row=1, column=1, sticky='ew', pady=3)
            self._local_browse.grid(row=1, column=2, padx=(6, 0), pady=3)
            # Hide ADB widgets
            self._adb_dev_lbl.grid_remove()
            self._adb_dev_combo.grid_remove()
            self._adb_dev_btns.grid_remove()
            self._adb_dir_lbl.grid_remove()
            self._adb_dir_entry.grid_remove()
            self._adb_dir_btns.grid_remove()
            self._adb_push_frame.grid_remove()
        else:
            # Hide local widgets
            self._local_lbl.grid_remove()
            self._local_entry.grid_remove()
            self._local_browse.grid_remove()
            # Show ADB widgets
            self._adb_dev_lbl.grid(row=1, column=0, sticky='e', padx=(0, 6), pady=3)
            self._adb_dev_combo.grid(row=1, column=1, sticky='ew', pady=3)
            self._adb_dev_btns.grid(row=1, column=2, padx=(6, 0), pady=3)
            self._adb_dir_lbl.grid(row=2, column=0, sticky='e', padx=(0, 6), pady=3)
            self._adb_dir_entry.grid(row=2, column=1, sticky='ew', pady=3)
            self._adb_dir_btns.grid(row=2, column=2, padx=(6, 0), pady=3)
            self._adb_push_frame.grid(row=3, column=0, columnspan=3,
                                      sticky='ew', pady=3)
            # Auto-refresh device list
            self._refresh_adb_devices()

    def _refresh_adb_devices(self):
        """Populate the device combobox with connected ADB devices."""
        if not self._adb:
            self._adb_dev_combo['values'] = ['(ADB not found)']
            self._adb_dev_combo.set('(ADB not found)')
            return

        devices = list_devices(self._adb)
        if not devices:
            self._adb_dev_combo['values'] = ['(no devices)']
            self._adb_dev_combo.set('(no devices)')
            return

        labels = []
        serials = []
        for d in devices:
            model = d['model'] or d['device'] or d['serial']
            label = f"{model} ({d['serial']})"
            labels.append(label)
            serials.append(d['serial'])

        self._adb_dev_combo['values'] = labels
        self._adb_device_serials = serials

        # Restore previous selection if still connected
        prev = self._adb_serial.get()
        if prev in serials:
            idx = serials.index(prev)
            self._adb_dev_combo.current(idx)
        else:
            self._adb_dev_combo.current(0)
            self._adb_serial.set(serials[0])

        # Bind selection to update serial
        self._adb_dev_combo.bind('<<ComboboxSelected>>',
                                 self._on_device_selected)

    def _on_device_selected(self, _event=None):
        """Update the stored serial when the user picks a device."""
        idx = self._adb_dev_combo.current()
        if hasattr(self, '_adb_device_serials') and 0 <= idx < len(self._adb_device_serials):
            self._adb_serial.set(self._adb_device_serials[idx])

    # ── Device folder browser ────────────────────────────────────────────────

    def _browse_device_folder(self):
        """Open a dialog to browse folders on the ADB device."""
        self._open_device_browser(self._adb_remote_dir)

    def _browse_device_push_folder(self):
        """Open a dialog to browse folders on the ADB device for push target."""
        self._open_device_browser(self._adb_push_dir)

    def _open_device_browser(self, target_var: tk.StringVar):
        """Tree-view dialog for browsing device folders."""
        serial = self._adb_serial.get()
        if not self._adb or not serial or serial.startswith('('):
            messagebox.showwarning('No Device',
                                   'Connect an ADB device first.')
            return

        dlg = tk.Toplevel(self)
        dlg.title('Browse Device Folder')
        dlg.geometry('500x450')
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text='Select a folder on the device',
                 font=('Segoe UI', 11, 'bold'), bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=12, pady=(10, 2))

        # Quick-nav buttons — auto-detect storage volumes on the device
        nav = tk.Frame(dlg, bg=BG)
        nav.pack(fill='x', padx=12, pady=(0, 6))

        nav_items = [('Internal', '/sdcard')]
        # Detect SD card and other volumes under /storage
        sd_paths = []
        storage_entries = list_directory(self._adb, serial, '/storage')
        for e in storage_entries:
            if not e['is_dir']:
                continue
            name = e['name']
            # Skip internal storage aliases and Android internals
            if name in ('emulated', 'self'):
                continue
            # This is likely an SD card (e.g. "3830-6461")
            sd_path = f'/storage/{name}'
            nav_items.append(('SD Card', sd_path))
            sd_paths.append(sd_path)

        # Add Roms folder shortcuts (check SD cards first, then internal)
        for base in sd_paths + ['/sdcard']:
            for roms_name in ('Roms', 'roms', 'RetroArch/roms'):
                check_path = f'{base}/{roms_name}'
                probe = list_directory(self._adb, serial, check_path)
                if probe:
                    label = 'SD Roms' if base != '/sdcard' else 'Roms'
                    nav_items.append((label, check_path))
                    break

        for label, path in nav_items:
            tk.Button(nav, text=label,
                      command=lambda p=path: _navigate(p),
                      bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                      font=('Segoe UI', 8), activebackground='#3A3A5D'
                      ).pack(side='left', padx=(0, 4))

        # Current path display
        path_var = tk.StringVar(value='/sdcard')
        path_frame = tk.Frame(dlg, bg=BG)
        path_frame.pack(fill='x', padx=12, pady=(0, 4))
        tk.Label(path_frame, text='Path:', bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 9)).pack(side='left')
        path_entry = tk.Entry(path_frame, textvariable=path_var,
                              bg=BG_ENTRY, fg=FG, insertbackground=FG,
                              relief='flat', font=('Segoe UI', 9))
        path_entry.pack(side='left', fill='x', expand=True, padx=(4, 4))
        tk.Button(path_frame, text='Go',
                  command=lambda: _navigate(path_var.get().strip()),
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='left')

        # Folder list
        list_frame = tk.Frame(dlg, bg=BG)
        list_frame.pack(fill='both', expand=True, padx=12, pady=(0, 6))
        listbox = tk.Listbox(list_frame, bg=BG_PANEL, fg=FG,
                             font=('Consolas', 10), relief='flat',
                             selectbackground='#313155', selectforeground=FG)
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        current_entries = []

        def _navigate(path):
            path = path.rstrip('/')
            if not path:
                path = '/'
            path_var.set(path)
            listbox.delete(0, 'end')
            current_entries.clear()

            # Add parent entry
            if path != '/':
                listbox.insert('end', '  ..')
                current_entries.append({'name': '..', 'is_dir': True})

            entries = list_directory(self._adb, serial, path)
            for e in entries:
                prefix = '  📁 ' if e['is_dir'] else '  📄 '
                listbox.insert('end', prefix + e['name'])
                current_entries.append(e)

            if not entries and path != '/':
                listbox.insert('end', '  (empty or inaccessible)')

        def _on_double_click(_event):
            sel = listbox.curselection()
            if not sel:
                return
            entry = current_entries[sel[0]]
            if not entry['is_dir']:
                return
            cur = path_var.get().rstrip('/')
            if entry['name'] == '..':
                parent = '/'.join(cur.split('/')[:-1])
                _navigate(parent or '/')
            else:
                _navigate(cur + '/' + entry['name'])

        listbox.bind('<Double-1>', _on_double_click)

        # Buttons
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(fill='x', padx=12, pady=(0, 10))
        tk.Button(btn_frame, text='Select This Folder', width=16,
                  command=lambda: _select(),
                  bg=SUCCESS, fg=BG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), activebackground='#8DC98A'
                  ).pack(side='right', padx=(8, 0))
        tk.Button(btn_frame, text='Cancel', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10), activebackground='#3A3A5D'
                  ).pack(side='right')

        def _select():
            target_var.set(path_var.get().strip())
            dlg.destroy()

        # Initial navigation
        initial = target_var.get().strip() or '/sdcard'
        _navigate(initial)

    # ── Browse / Open handlers ────────────────────────────────────────────────

    def _browse_input(self):
        d = filedialog.askdirectory(title='Select ROM Folder')
        if d:
            self._input_var.set(d)

    def _browse_filter(self):
        """Browse for a filter folder or text file."""
        what = messagebox.askyesnocancel(
            'Filter Source',
            'Yes  →  Pick a folder (supports MTP devices)\n'
            'No   →  Pick a text file (.txt, one name per line)',
        )
        if what is None:
            return
        if what:
            self._browse_filter_folder()
        else:
            f = filedialog.askopenfilename(
                title='Select filter list (.txt)',
                filetypes=[('Text files', '*.txt'), ('All files', '*.*')])
            if f:
                self._filter_var.set(f)

    def _browse_filter_folder(self):
        """Use Windows Shell COM dialog to pick a folder (supports MTP)."""
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', '''
$shell = New-Object -ComObject Shell.Application
$folder = $shell.BrowseForFolder(0, "Select Filter Folder (MTP devices supported)", 0x40, 17)
if ($folder -ne $null) {
    $items = $folder.Items()
    $names = @()
    foreach ($item in $items) { $names += $item.Name }
    if ($names.Count -gt 0) {
        $tmp = [System.IO.Path]::GetTempFileName()
        $tmp = $tmp -replace '\.tmp$', '.txt'
        $names | Out-File -Encoding UTF8NoBOM -FilePath $tmp
        Write-Output "FILE:$tmp"
    }
    # Also try to get a filesystem path
    $path = $folder.Self.Path
    if ($path -and (Test-Path $path -PathType Container)) {
        Write-Output "PATH:$path"
    }
}
'''],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                # Fallback to tkinter
                d = filedialog.askdirectory(title='Select Filter Folder')
                if d:
                    self._filter_var.set(d)
                return

            fs_path = None
            txt_path = None
            for line in result.stdout.strip().splitlines():
                if line.startswith('PATH:'):
                    fs_path = line[5:]
                elif line.startswith('FILE:'):
                    txt_path = line[5:]

            # Prefer the filesystem path if available (local/network folder)
            if fs_path:
                self._filter_var.set(fs_path)
            elif txt_path:
                # MTP device — use the generated txt file
                self._filter_var.set(txt_path)
                self._log_msg(f'MTP device: saved {txt_path}')

        except Exception:
            # Fallback to tkinter
            d = filedialog.askdirectory(title='Select Filter Folder')
            if d:
                self._filter_var.set(d)

    @staticmethod
    def _load_filter_stems(path: str) -> set | None:
        """Load filter stems from a folder or text file.

        Returns a set of lowercase stems, or None on failure.
        """
        stems = set()

        if os.path.isfile(path) and path.lower().endswith('.txt'):
            # Text file: one ROM name per line
            with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    name = line.strip()
                    if not name:
                        continue
                    stem = os.path.splitext(name)[0]
                    stems.add(stem.lower())
                    inner = os.path.splitext(stem)[0]
                    if inner != stem:
                        stems.add(inner.lower())
        elif os.path.isdir(path):
            for name in os.listdir(path):
                stem = os.path.splitext(name)[0]
                stems.add(stem.lower())
                inner = os.path.splitext(stem)[0]
                if inner != stem:
                    stems.add(inner.lower())
        else:
            return None

        return stems if stems else None

    def _open_output(self):
        os.makedirs(OUTPUT_BASE, exist_ok=True)
        subprocess.Popen(f'explorer "{OUTPUT_BASE}"')

    # ── Scan ─────────────────────────────────────────────────────────────────

    def _on_scan(self):
        mode = self._source_mode.get()

        if mode == 'adb':
            self._on_scan_adb()
            return

        folder = self._input_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning('No Folder', 'Please select a valid ROM folder first.')
            return

        filter_dir = self._filter_var.get().strip()
        save_config(last_input_dir=folder,
                    last_filter_dir=filter_dir if filter_dir else None,
                    last_source_mode=mode)

        self._tree.delete(*self._tree.get_children())
        self._rom_paths = []
        self._adb_remote_paths = []
        self._progress['value'] = 0
        self._status_var.set('Scanning…')
        self.update_idletasks()

        roms = scan_directory(folder, self._recursive_var.get())

        # Apply filter: only keep ROMs whose stem matches the filter list.
        # Filter source can be a folder (filenames) or a .txt file (one name per line).
        if filter_dir and (os.path.isdir(filter_dir) or os.path.isfile(filter_dir)):
            filter_stems = self._load_filter_stems(filter_dir)
            if filter_stems is not None:
                before = len(roms)
                roms = [r for r in roms if r.stem.lower() in filter_stems]
                self._log_msg(
                    f'Filter applied: {len(roms)} of {before} ROMs matched '
                    f'{len(filter_stems)} names from {filter_dir!r}')

        self._rom_paths = [str(r) for r in roms]

        for path in roms:
            ext      = os.path.splitext(str(path))[1].lower()
            stem     = game_stem(str(path), ext)
            platform = get_platform(str(path))

            mp3_exists = os.path.isfile(get_mp3_path(str(path), ext))
            status = 'Already Done' if mp3_exists else 'Pending'
            tag    = 'exists'       if mp3_exists else 'pending'

            self._tree.insert('', 'end', iid=str(path),
                              values=('\u2611', stem, platform, status),
                              tags=(tag, 'selected'))

        n = len(roms)
        self._count_var.set(f'{n} ROM{"s" if n != 1 else ""} found')
        self._status_var.set(f'Scan complete: {n} ROMs')
        if n > 0:
            self._start_btn.config(state='normal')
        self._log_msg(f'Scanned {folder!r}: {n} ROMs found.')

    def _on_scan_adb(self):
        """Scan ROMs on the connected ADB device."""
        serial = self._adb_serial.get()
        remote_dir = self._adb_remote_dir.get().strip()
        if not self._adb or not serial or serial.startswith('('):
            messagebox.showwarning('No Device',
                                   'Connect an ADB device and select it first.')
            return
        if not remote_dir:
            messagebox.showwarning('No Folder',
                                   'Enter or browse to a folder on the device.')
            return

        filter_dir = self._filter_var.get().strip()
        save_config(last_adb_serial=serial,
                    last_adb_remote_dir=remote_dir,
                    last_adb_push_dir=self._adb_push_dir.get().strip(),
                    last_filter_dir=filter_dir if filter_dir else None,
                    last_source_mode='adb')

        self._tree.delete(*self._tree.get_children())
        self._rom_paths = []
        self._adb_remote_paths = []
        self._progress['value'] = 0
        self._status_var.set('Scanning device…')
        self.update_idletasks()

        self._log_msg(f'Scanning ADB device {serial}: {remote_dir}')
        remote_roms = scan_device_roms(
            self._adb, serial, remote_dir, self._recursive_var.get())

        # Apply filter
        if filter_dir and (os.path.isdir(filter_dir) or os.path.isfile(filter_dir)):
            filter_stems = self._load_filter_stems(filter_dir)
            if filter_stems is not None:
                before = len(remote_roms)
                remote_roms = [
                    r for r in remote_roms
                    if os.path.splitext(os.path.basename(r))[0].lower() in filter_stems
                ]
                self._log_msg(
                    f'Filter applied: {len(remote_roms)} of {before} ROMs matched')

        self._adb_remote_paths = remote_roms
        # Use remote paths as iids, but store a parallel rom_paths list
        # that will be filled with local cached paths at start time.
        self._rom_paths = remote_roms  # placeholder — replaced during pull

        from pathlib import PurePosixPath
        for rpath in remote_roms:
            posix = PurePosixPath(rpath)
            stem = os.path.splitext(posix.name)[0]
            ext = posix.suffix.lower()
            platform = get_platform(rpath)

            # Check if MP3 already exists locally
            mp3_exists = os.path.isfile(get_mp3_path(rpath, ext))
            status = 'Already Done' if mp3_exists else 'Pending'
            tag    = 'exists'       if mp3_exists else 'pending'

            self._tree.insert('', 'end', iid=rpath,
                              values=('\u2611', stem, platform, status),
                              tags=(tag, 'selected'))

        n = len(remote_roms)
        self._count_var.set(f'{n} ROM{"s" if n != 1 else ""} found')
        self._status_var.set(f'Scan complete: {n} ROMs on device')
        if n > 0:
            self._start_btn.config(state='normal')
        self._log_msg(f'Found {n} ROMs on device in {remote_dir!r}.')

    # ── Start / Stop ─────────────────────────────────────────────────────────

    def _on_start(self):
        if not self._rom_paths:
            messagebox.showinfo('Nothing to do', 'Scan a ROM folder first.')
            return

        # Only process selected (checked) ROMs
        selected_paths = [
            iid for iid in self._tree.get_children()
            if 'selected' in self._tree.item(iid, 'tags')
        ]
        if not selected_paths:
            messagebox.showinfo('Nothing selected',
                                'No ROMs are selected. Use the checkboxes to select ROMs.')
            return

        if not self._ffmpeg:
            if not messagebox.askyesno(
                'FFmpeg Missing',
                'FFmpeg was not found. Format-specific banner extraction will\n'
                'still work, but generic fallback will be unavailable.\n\nContinue?'
            ):
                return

        self._start_btn.config(state='disabled')
        self._stop_btn.config(state='normal')
        self._scan_btn.config(state='disabled')
        self._progress['value'] = 0

        # Clear the log
        self._log.config(state='normal')
        self._log.delete('1.0', 'end')
        self._log.config(state='disabled')

        for iid in self._tree.get_children():
            vals = self._tree.item(iid, 'values')
            if 'selected' in self._tree.item(iid, 'tags') and vals[3] != 'Already Done':
                tags = [t for t in self._tree.item(iid, 'tags') if t != 'pending']
                tags.append('pending')
                self._tree.item(iid, values=(vals[0], vals[1], vals[2], 'Pending'),
                                tags=tags)

        if self._source_mode.get() == 'adb':
            self._start_adb_pull(selected_paths)
        else:
            self._start_worker(selected_paths)

    def _start_worker(self, rom_paths: list):
        """Launch the processing worker on local ROM paths."""
        self._worker = ProcessingWorker(
            rom_paths=rom_paths,
            ffmpeg_path=self._ffmpeg,
            seven_zip_path=self._7z,
            vgmstream_path=self._vgmstream,
            retroarch_path=self._retroarch,
            retroarch_cores=self._retroarch_cores,
            msg_queue=self._msg_queue,
        )
        self._worker.start()
        self._log_msg(f'Processing {len(rom_paths)} ROMs → {OUTPUT_BASE}')

    # ── ADB pull phase ───────────────────────────────────────────────────────

    def _start_adb_pull(self, selected_remote_paths: list):
        """Pull selected ROMs from ADB device, then start the worker."""
        import threading

        serial = self._adb_serial.get()
        self._adb_cache = AdbRomCache(self._adb, serial)
        self._cancel_event = threading.Event()

        self._log_msg(f'Pulling {len(selected_remote_paths)} ROMs from device…')
        self._status_var.set('Pulling from device…')

        def _pull_thread():
            total = len(selected_remote_paths)
            local_paths = []    # (remote_path, local_path) pairs
            failed_pulls = []

            for i, rpath in enumerate(selected_remote_paths):
                if self._cancel_event.is_set():
                    self._msg_queue.put(('log', 'ADB pull cancelled.'))
                    self._msg_queue.put(('adb_pull_done', ([], failed_pulls, True)))
                    return

                stem = os.path.splitext(os.path.basename(rpath))[0]
                self._msg_queue.put(('progress', (i, total, f'Pull: {stem}')))
                self._msg_queue.put(('file_status', (rpath, 'Pulling…')))

                local = self._adb_cache.ensure_local(
                    rpath, cancel_event=self._cancel_event)
                if local:
                    local_paths.append((rpath, local))
                    self._msg_queue.put(('file_status', (rpath, 'Pending')))
                else:
                    failed_pulls.append(rpath)
                    self._msg_queue.put(('file_status', (rpath, 'Pull Failed')))
                    self._msg_queue.put(('log', f'Failed to pull: {stem}'))

            self._msg_queue.put(('progress', (total, total, '')))
            self._msg_queue.put(('adb_pull_done', (local_paths, failed_pulls, False)))

        self._adb_pull_thread = threading.Thread(target=_pull_thread, daemon=True)
        self._adb_pull_thread.start()

    def _start_adb_push(self, mp3_paths: list):
        """Push generated MP3s back to the device after processing."""
        import threading

        serial = self._adb_serial.get()
        push_dir = self._adb_push_dir.get().strip()
        if not push_dir or not serial:
            return

        self._log_msg(f'Pushing {len(mp3_paths)} MP3s to device: {push_dir}')
        self._status_var.set('Pushing to device…')

        def _push_thread():
            total = len(mp3_paths)
            pushed = 0
            for i, local_mp3 in enumerate(mp3_paths):
                if not os.path.isfile(local_mp3):
                    continue
                basename = os.path.basename(local_mp3)
                # Preserve platform subfolder structure
                rel = os.path.relpath(local_mp3, OUTPUT_BASE)
                remote_target = push_dir.rstrip('/') + '/' + rel.replace('\\', '/')

                self._msg_queue.put(('progress', (i, total, f'Push: {basename}')))
                if push_file(self._adb, serial, local_mp3, remote_target):
                    pushed += 1
                else:
                    self._msg_queue.put(('log', f'Push failed: {basename}'))

            self._msg_queue.put(('progress', (total, total, '')))
            self._msg_queue.put(('log',
                f'Pushed {pushed}/{total} MP3s to {push_dir}'))
            self._msg_queue.put(('adb_push_done', pushed))

        self._adb_push_thread = threading.Thread(target=_push_thread, daemon=True)
        self._adb_push_thread.start()

    def _on_stop(self):
        # Cancel ADB pull/push if in progress
        if hasattr(self, '_cancel_event'):
            self._cancel_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.cancel()
            self._status_var.set('Stopping…')
            self._stop_btn.config(state='disabled')

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg_type, data = self._msg_queue.get_nowait()
                self._handle_msg(msg_type, data)
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._poll_queue)

    def _handle_msg(self, msg_type: str, data):
        if msg_type == 'progress':
            idx, total, stem = data
            if total > 0:
                self._progress['value'] = (idx / total) * 100
            self._status_var.set(
                f'[{idx + 1}/{total}] {stem[:50]}' if stem else f'Done ({total} files)')

        elif msg_type == 'adb_pull_done':
            local_paths, failed_pulls, cancelled = data
            if cancelled:
                self._status_var.set('Pull cancelled')
                self._start_btn.config(state='normal')
                self._stop_btn.config(state='disabled')
                self._scan_btn.config(state='normal')
                return
            if not local_paths:
                self._log_msg('No ROMs were pulled successfully.')
                self._status_var.set('Pull failed')
                self._start_btn.config(state='normal')
                self._stop_btn.config(state='disabled')
                self._scan_btn.config(state='normal')
                return
            # Build reverse mapping: local cached path → remote path (tree iid)
            self._adb_local_to_remote = {lp: rp for rp, lp in local_paths}
            worker_paths = [lp for _, lp in local_paths]
            self._log_msg(
                f'Pulled {len(local_paths)} ROMs '
                f'({len(failed_pulls)} failed). Starting extraction…')
            self._start_worker(worker_paths)
            return

        elif msg_type == 'adb_push_done':
            self._status_var.set(f'Done — {data} MP3s pushed to device')
            self._start_btn.config(state='normal')
            self._stop_btn.config(state='disabled')
            self._scan_btn.config(state='normal')
            return

        elif msg_type == 'file_status':
            rom_path, status = data
            # In ADB mode the worker uses local cached paths, but tree iids
            # are remote paths.  Resolve via the reverse map.
            tree_iid = rom_path
            if hasattr(self, '_adb_local_to_remote'):
                tree_iid = self._adb_local_to_remote.get(rom_path, rom_path)
            tag = {
                'Done':          'done',
                'Already Done':  'exists',
                'Error':         'error',
                'No Audio':      'noaudio',
                'Processing...': 'proc',
                'Pending':       'pending',
                'Pulling…':      'proc',
                'Pull Failed':   'error',
            }.get(status, 'pending')
            try:
                vals = self._tree.item(tree_iid, 'values')
                old_tags = self._tree.item(tree_iid, 'tags')
                # Preserve the 'selected' tag
                new_tags = [tag]
                if 'selected' in old_tags:
                    new_tags.append('selected')
                self._tree.item(tree_iid,
                                values=(vals[0], vals[1], vals[2], status),
                                tags=new_tags)
                self._tree.see(tree_iid)
            except tk.TclError:
                pass

        elif msg_type == 'log':
            self._log_msg(data)

        elif msg_type == 'done':
            success, failed, skipped, total = data
            self._status_var.set(
                f'Finished: {success} done, {skipped} skipped, {failed} errors')
            self._progress['value'] = 100
            self._log_msg(
                f'--- Finished: {success}/{total} exported, '
                f'{skipped} skipped/no audio, {failed} errors ---')

            # Push MP3s back to device if ADB mode + push enabled
            if (self._source_mode.get() == 'adb' and
                    self._adb_push_var.get() and
                    self._adb_push_dir.get().strip() and
                    success > 0):
                # Collect MP3 paths for successfully processed ROMs
                mp3s = []
                for iid in self._tree.get_children():
                    vals = self._tree.item(iid, 'values')
                    if vals[3] == 'Done':
                        ext = os.path.splitext(iid)[1].lower()
                        mp3 = get_mp3_path(iid, ext)
                        if os.path.isfile(mp3):
                            mp3s.append(mp3)
                if mp3s:
                    self._start_adb_push(mp3s)
                    return  # Don't re-enable buttons yet; push handler will

            self._start_btn.config(state='normal')
            self._stop_btn.config(state='disabled')
            self._scan_btn.config(state='normal')

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_tree_click(self, event):
        """Toggle selection checkbox when clicking the first column."""
        region = self._tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        col = self._tree.identify_column(event.x)
        if col != '#1':  # Only toggle on the checkbox column
            return
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        tags = list(self._tree.item(iid, 'tags'))
        vals = list(self._tree.item(iid, 'values'))
        if 'selected' in tags:
            tags.remove('selected')
            vals[0] = '\u2610'   # ☐ unchecked
        else:
            tags.append('selected')
            vals[0] = '\u2611'   # ☑ checked
        self._tree.item(iid, values=vals, tags=tags)
        self._update_count()

    def _on_tree_right_click(self, event):
        """Show a context menu when right-clicking a ROM row."""
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        # Select the row under the cursor for visual feedback
        self._tree.selection_set(iid)

        rom_path = iid
        matching_rule = self._find_matching_rule_smart(rom_path)

        menu = tk.Menu(self, tearoff=0,
                       bg=BG_PANEL, fg=FG,
                       activebackground='#3A3A5D', activeforeground=FG,
                       bd=0)

        if matching_rule:
            rule_name = matching_rule.get('name', '(unnamed)')
            menu.add_command(
                label=f'Edit rule: {rule_name}',
                command=lambda: self._edit_matching_rule(rom_path))
            menu.add_command(
                label=f'Delete rule: {rule_name}',
                foreground=ERROR,
                command=lambda: self._delete_matching_rule(rom_path))
        else:
            menu.add_command(
                label='Create new rule from this ROM…',
                command=lambda: self._create_rule_from_rom(rom_path))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _find_matching_rule_smart(self, rom_path: str) -> dict:
        """Find a matching rule using archive-aware platform detection.

        Like settings._matching_rule but peeks inside .zip/.7z archives
        to determine the real platform of the ROM inside.
        """
        import settings as settings_mod
        import re as _re

        rules = settings_mod.get_rules()
        if not rules:
            return None

        name = os.path.basename(rom_path)
        real_platform = self._detect_rom_platform(rom_path)

        for rule in rules:
            pattern = rule.get('pattern', '').strip()
            if not pattern:
                continue

            platforms = rule.get('platforms', [])
            if platforms and real_platform not in platforms:
                continue

            try:
                if rule.get('regex', False):
                    if _re.search(pattern, name, _re.IGNORECASE):
                        return rule
                else:
                    if pattern.lower() in name.lower():
                        return rule
            except _re.error:
                continue
        return None

    def _edit_matching_rule(self, rom_path: str):
        """Open the rule editor for the rule that currently matches a ROM."""
        import settings as settings_mod
        rules = settings_mod.get_rules()
        matching = self._find_matching_rule_smart(rom_path)
        if matching is None:
            return

        idx = self._find_rule_index(rules, matching)
        if idx is None:
            return

        def _save(updated_rule):
            current = settings_mod.get_rules()
            if 0 <= idx < len(current):
                current[idx] = updated_rule
                settings_mod.save_rules(current)
                self._log_msg(
                    f'Updated rule: {updated_rule.get("name", "")}')

        self._open_rule_editor(self, rules[idx], on_save=_save)

    def _delete_matching_rule(self, rom_path: str):
        """Delete the rule that currently matches a ROM (with confirmation)."""
        import settings as settings_mod
        rules = settings_mod.get_rules()
        matching = self._find_matching_rule_smart(rom_path)
        if matching is None:
            return

        idx = self._find_rule_index(rules, matching)
        if idx is None:
            return

        rule_name = rules[idx].get('name', '(unnamed)')
        if not messagebox.askyesno(
                'Delete rule',
                f'Delete rule "{rule_name}"?'):
            return

        del rules[idx]
        settings_mod.save_rules(rules)
        self._log_msg(f'Deleted rule: {rule_name}')

    @staticmethod
    def _find_rule_index(rules: list, target: dict):
        """Return the index of a rule dict in a list, or None."""
        try:
            return next(i for i, r in enumerate(rules)
                        if r is target or (
                            r.get('name') == target.get('name') and
                            r.get('pattern') == target.get('pattern')))
        except StopIteration:
            return None

    def _detect_rom_platform(self, rom_path: str) -> str:
        """Return the platform for a ROM, peeking inside archives if needed."""
        ext = os.path.splitext(rom_path)[1].lower()

        # For .zip archives, peek inside to find the inner ROM extension
        if ext == '.zip':
            try:
                import zipfile
                with zipfile.ZipFile(rom_path) as zf:
                    for name in zf.namelist():
                        inner_ext = os.path.splitext(name)[1].lower()
                        if inner_ext in SUPPORTED_EXTENSIONS and \
                                inner_ext not in ('.zip', '.7z'):
                            # Use the inner file path for platform detection
                            # so folder hints (e.g. PlayStation 2) still apply
                            inner_path = os.path.join(
                                os.path.dirname(rom_path), name)
                            return get_platform(inner_path)
            except Exception:
                pass

        # For .7z, try to list contents via the bundled 7z.exe
        if ext == '.7z' and self._7z:
            try:
                import subprocess
                r = subprocess.run(
                    [self._7z, 'l', '-slt', rom_path],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                for line in r.stdout.splitlines():
                    if line.startswith('Path = '):
                        name = line[7:].strip()
                        inner_ext = os.path.splitext(name)[1].lower()
                        if inner_ext in SUPPORTED_EXTENSIONS and \
                                inner_ext not in ('.zip', '.7z'):
                            inner_path = os.path.join(
                                os.path.dirname(rom_path), name)
                            return get_platform(inner_path)
            except Exception:
                pass

        # Otherwise use the ROM's own extension
        return get_platform(rom_path)

    def _create_rule_from_rom(self, rom_path: str):
        """Open the rule editor with fields pre-filled from a ROM path."""
        import settings as settings_mod

        stem = os.path.splitext(os.path.basename(rom_path))[0]
        # Strip common region/version tags to get a cleaner default pattern
        import re as _re
        clean_stem = _re.sub(r'\s*\([^)]*\)', '', stem).strip()
        if not clean_stem:
            clean_stem = stem

        platform = self._detect_rom_platform(rom_path)
        # Filter out non-game "platforms" like archive types or Unknown
        non_game = {'ZIP Archive', '7-Zip Archive', 'Unknown',
                    'Disc Image', 'CD Image', 'CHD Disc'}
        platforms = [platform] if platform and platform not in non_game else []

        starter = {
            'name': clean_stem or 'New rule',
            'pattern': clean_stem.lower() or stem.lower(),
            'regex': False,
            'platforms': platforms,
            'overrides': {},
        }

        def _save(new_rule):
            current = settings_mod.get_rules()
            current.append(new_rule)
            settings_mod.save_rules(current)
            self._log_msg(
                f'Added rule: {new_rule.get("name", "")}')

        self._open_rule_editor(self, starter, on_save=_save, is_new=True)

    def _select_all(self):
        for iid in self._tree.get_children():
            tags = list(self._tree.item(iid, 'tags'))
            vals = list(self._tree.item(iid, 'values'))
            if 'selected' not in tags:
                tags.append('selected')
            vals[0] = '\u2611'
            self._tree.item(iid, values=vals, tags=tags)
        self._update_count()

    def _deselect_all(self):
        for iid in self._tree.get_children():
            tags = list(self._tree.item(iid, 'tags'))
            vals = list(self._tree.item(iid, 'values'))
            if 'selected' in tags:
                tags.remove('selected')
            vals[0] = '\u2610'
            self._tree.item(iid, values=vals, tags=tags)
        self._update_count()

    def _update_count(self):
        total = len(self._tree.get_children())
        selected = sum(1 for iid in self._tree.get_children()
                       if 'selected' in self._tree.item(iid, 'tags'))
        self._count_var.set(f'{selected}/{total} ROMs selected')

    def _on_search(self):
        """Highlight matching rows and show match count."""
        query = self._search_var.get().strip().lower()
        if not query:
            self._match_count_var.set('')
            # Remove highlight from all
            for iid in self._tree.get_children():
                self._tree.item(iid, tags=[
                    t for t in self._tree.item(iid, 'tags') if t != 'highlight'])
            return
        count = 0
        first = None
        for iid in self._tree.get_children():
            vals = self._tree.item(iid, 'values')
            name = vals[1].lower() if len(vals) > 1 else ''
            tags = [t for t in self._tree.item(iid, 'tags') if t != 'highlight']
            if query in name:
                tags.append('highlight')
                count += 1
                if first is None:
                    first = iid
            self._tree.item(iid, tags=tags)
        self._match_count_var.set(f'{count} matches')
        if first:
            self._tree.see(first)

    def _select_matches(self, select: bool):
        """Select or deselect all ROMs matching the current search."""
        query = self._search_var.get().strip().lower()
        if not query:
            return
        for iid in self._tree.get_children():
            vals = list(self._tree.item(iid, 'values'))
            name = vals[1].lower() if len(vals) > 1 else ''
            if query in name:
                tags = list(self._tree.item(iid, 'tags'))
                if select and 'selected' not in tags:
                    tags.append('selected')
                    vals[0] = '\u2611'
                elif not select and 'selected' in tags:
                    tags.remove('selected')
                    vals[0] = '\u2610'
                self._tree.item(iid, values=vals, tags=tags)
        self._update_count()

    # ── Game Rules manager ───────────────────────────────────────────────────

    def _open_rules_manager(self):
        """Open the Game-Specific Rules manager dialog."""
        import settings as settings_mod

        dlg = tk.Toplevel(self)
        dlg.title('Game Rules')
        dlg.geometry('920x500')
        dlg.minsize(840, 400)
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text='Game-Specific Rules',
                 font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(dlg,
                 text='Override settings for ROMs whose filename matches '
                      'a pattern. Useful for series with longer intro '
                      'audio (e.g. Pokemon, Final Fantasy). Rules are '
                      'checked in order — the first match wins.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9),
                 wraplength=600, justify='left'
                 ).pack(anchor='w', padx=16, pady=(0, 8))

        # Pack the button frame BEFORE the rules list so it stays
        # anchored to the bottom regardless of how the list expands.
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(side='bottom', fill='x', padx=16, pady=(8, 12))

        # Rules grid — custom Frame-based layout with real Button widgets
        # for the inline edit/delete actions (Treeview can't color
        # individual cells or attach hover cursors to columns).
        list_outer = tk.Frame(dlg, bg=BG_PANEL, bd=1, relief='solid',
                              highlightbackground=BG_ENTRY)
        list_outer.pack(fill='both', expand=True, padx=16, pady=4)

        # Header row (fixed, not scrollable)
        header = tk.Frame(list_outer, bg=BG_ENTRY)
        header.pack(fill='x', side='top')

        col_specs = [
            # (key, label, width, anchor)
            ('name',      'Name',      180, 'w'),
            ('kind',      'Match',      80, 'center'),
            ('pattern',   'Pattern',   180, 'w'),
            ('platforms', 'Platforms', 140, 'w'),
            ('overrides', 'Overrides',  80, 'center'),
            ('edit',      '',           36, 'center'),
            ('delete',    '',           36, 'center'),
        ]
        for key, label, width, anchor in col_specs:
            tk.Label(header, text=label, bg=BG_ENTRY, fg=ACCENT,
                     font=('Segoe UI', 9, 'bold'),
                     width=width // 8, anchor=anchor
                     ).pack(side='left', padx=4, pady=4)

        # Scrollable body
        body_outer = tk.Frame(list_outer, bg=BG_PANEL)
        body_outer.pack(fill='both', expand=True)

        canvas = tk.Canvas(body_outer, bg=BG_PANEL, highlightthickness=0)
        vsb = ttk.Scrollbar(body_outer, orient='vertical',
                            command=canvas.yview)
        body_inner = tk.Frame(canvas, bg=BG_PANEL)
        body_inner.bind(
            '<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=body_inner, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        empty_label = tk.Label(
            canvas,
            text='No rules defined. Click "+ Add Rule" to create one.',
            bg=BG_PANEL, fg=FG_DIM, font=('Segoe UI', 10, 'italic'))

        def _refresh_rules_list():
            for w in body_inner.winfo_children():
                w.destroy()
            current_rules = settings_mod.get_rules()
            if not current_rules:
                empty_label.place(relx=0.5, rely=0.5, anchor='center')
                return
            else:
                empty_label.place_forget()

            for idx, rule in enumerate(current_rules):
                pattern = rule.get('pattern', '')
                kind = 'regex' if rule.get('regex') else 'substring'
                count = len(rule.get('overrides', {}))
                name = rule.get('name', '(unnamed)')
                platforms = rule.get('platforms', [])
                if not platforms:
                    plat_text = 'any'
                elif len(platforms) == 1:
                    plat_text = platforms[0]
                else:
                    plat_text = f'{len(platforms)} platforms'

                row_bg = BG_PANEL if idx % 2 == 0 else '#1F1F2F'
                row = tk.Frame(body_inner, bg=row_bg)
                row.pack(fill='x')

                values = [name, kind, pattern, plat_text, str(count)]
                for (key, _label, width, anchor), val in zip(col_specs[:5],
                                                              values):
                    fg = FG_DIM if key in ('kind', 'platforms') else FG
                    tk.Label(row, text=val, bg=row_bg, fg=fg,
                             font=('Segoe UI', 9),
                             width=width // 8, anchor=anchor
                             ).pack(side='left', padx=4, pady=4)

                # Inline action buttons
                edit_btn = tk.Button(
                    row, text='Edit', bg=row_bg, fg=ACCENT,
                    activebackground='#3A3A5D', activeforeground=ACCENT,
                    relief='flat', bd=0, cursor='hand2',
                    font=('Segoe UI', 9, 'underline'),
                    command=lambda i=idx: _edit_rule(i))
                edit_btn.pack(side='left', padx=4, pady=4)

                del_btn = tk.Button(
                    row, text='Delete', bg=row_bg, fg=ERROR,
                    activebackground='#3A3A5D', activeforeground=ERROR,
                    relief='flat', bd=0, cursor='hand2',
                    font=('Segoe UI', 9, 'underline'),
                    command=lambda i=idx: _delete_rule(i))
                del_btn.pack(side='left', padx=4, pady=4)

        # Mouse wheel scrolling for the rules canvas
        def _on_rules_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_rules_mousewheel)
        dlg.bind('<Destroy>',
                 lambda e: canvas.unbind_all('<MouseWheel>')
                 if e.widget == dlg else None)

        def _edit_rule(idx=None):
            rules = settings_mod.get_rules()
            existing = rules[idx] if idx is not None else None
            self._open_rule_editor(
                dlg, existing,
                on_save=lambda new_rule: _save_rule(idx, new_rule))

        def _save_rule(idx, new_rule):
            rules = settings_mod.get_rules()
            if idx is None:
                rules.append(new_rule)
            else:
                rules[idx] = new_rule
            settings_mod.save_rules(rules)
            _refresh_rules_list()

        def _delete_rule(idx):
            rules = settings_mod.get_rules()
            if 0 <= idx < len(rules):
                name = rules[idx].get('name', '(unnamed)')
                if messagebox.askyesno(
                        'Delete rule',
                        f'Delete rule "{name}"?', parent=dlg):
                    del rules[idx]
                    settings_mod.save_rules(rules)
                    _refresh_rules_list()

        def _export_rules():
            current_rules = settings_mod.get_rules()
            if not current_rules:
                messagebox.showinfo('No rules',
                                    'There are no rules to export.',
                                    parent=dlg)
                return
            path = filedialog.asksaveasfilename(
                parent=dlg,
                title='Export rules',
                defaultextension='.json',
                initialfile='jingles_rules.json',
                filetypes=[('JSON files', '*.json'),
                           ('All files', '*.*')])
            if not path:
                return
            try:
                count = settings_mod.export_rules(path)
                self._log_msg(f'Exported {count} rule(s) to {path}')
                messagebox.showinfo(
                    'Export complete',
                    f'Exported {count} rule(s) to:\n{path}', parent=dlg)
            except Exception as e:
                messagebox.showerror('Export failed', str(e), parent=dlg)

        def _import_rules():
            path = filedialog.askopenfilename(
                parent=dlg,
                title='Import rules',
                filetypes=[('JSON files', '*.json'),
                           ('All files', '*.*')])
            if not path:
                return
            try:
                imported = settings_mod.load_rules_file(path)
            except Exception as e:
                messagebox.showerror(
                    'Import failed',
                    f'Could not read rules file:\n{e}', parent=dlg)
                return

            if not imported:
                messagebox.showwarning(
                    'No rules found',
                    'The selected file did not contain any valid rules.',
                    parent=dlg)
                return

            current_count = len(settings_mod.get_rules())
            if current_count == 0:
                settings_mod.replace_rules(imported)
                self._log_msg(f'Imported {len(imported)} rule(s)')
                _refresh_rules_list()
                messagebox.showinfo(
                    'Import complete',
                    f'Imported {len(imported)} rule(s).', parent=dlg)
                return

            choice = messagebox.askyesnocancel(
                'Import rules',
                f'Found {len(imported)} rule(s) in the file.\n\n'
                f'Yes  →  Merge with your {current_count} existing rule(s) '
                f'(duplicates are renamed)\n'
                f'No   →  Replace all existing rules with the imported set\n'
                f'Cancel → Do nothing',
                parent=dlg)
            if choice is None:
                return
            if choice:
                added, renamed = settings_mod.merge_rules(imported)
                msg = f'Merged {added} rule(s)'
                if renamed:
                    msg += f' ({renamed} renamed to avoid conflicts)'
                self._log_msg(msg)
                messagebox.showinfo('Import complete', msg, parent=dlg)
            else:
                if not messagebox.askyesno(
                        'Replace all rules',
                        f'This will delete all {current_count} '
                        f'existing rule(s) and replace them with the '
                        f'{len(imported)} imported rule(s). Continue?',
                        parent=dlg):
                    return
                settings_mod.replace_rules(imported)
                msg = f'Replaced existing rules with {len(imported)} imported'
                self._log_msg(msg)
                messagebox.showinfo('Import complete', msg, parent=dlg)
            _refresh_rules_list()

        _refresh_rules_list()

        # Action buttons (btn_frame was created and packed at the
        # bottom of the dialog earlier; we just add buttons to it here).
        tk.Button(btn_frame, text='+ Add Rule',
                  command=lambda: _edit_rule(None),
                  bg=ACCENT, fg=BG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10, 'bold'),
                  activebackground='#74A8F0'
                  ).pack(side='left', padx=(0, 4))
        tk.Button(btn_frame, text='Export…',
                  command=_export_rules,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10),
                  activebackground='#3A3A5D'
                  ).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Import…',
                  command=_import_rules,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10),
                  activebackground='#3A3A5D'
                  ).pack(side='left', padx=4)

        tk.Button(btn_frame, text='Close', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10),
                  activebackground='#3A3A5D'
                  ).pack(side='right')

    # ── Settings dialog ──────────────────────────────────────────────────────

    def _open_settings(self):
        """Open a dialog to edit user-configurable defaults."""
        import settings as settings_mod

        dlg = tk.Toplevel(self)
        dlg.title('Settings')
        dlg.geometry('560x520')
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text='Settings', font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg=ACCENT).pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(dlg,
                 text='Defaults for output clipping and emulation timing. '
                      'Changes apply to the next file processed.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)
                 ).pack(anchor='w', padx=16)

        # Scrollable area
        outer = tk.Frame(dlg, bg=BG)
        outer.pack(fill='both', expand=True, padx=16, pady=8)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical',
                                  command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Group settings by their group field, in declaration order
        current = settings_mod.get_all()
        rows = {}  # key -> tk.StringVar holding the editable value

        seen_groups = []
        grouped = {}
        for key, (default, type_, label, desc, group) in settings_mod.DEFAULTS.items():
            if group not in grouped:
                grouped[group] = []
                seen_groups.append(group)
            grouped[group].append((key, default, type_, label, desc))

        for group in seen_groups:
            # Group header
            tk.Label(inner, text=group, font=('Segoe UI', 11, 'bold'),
                     bg=BG, fg=ACCENT
                     ).pack(anchor='w', pady=(8, 2))

            for key, default, type_, label, desc in grouped[group]:
                row = tk.Frame(inner, bg=BG)
                row.pack(fill='x', pady=2)

                tk.Label(row, text=label, bg=BG, fg=FG,
                         font=('Segoe UI', 9), width=28, anchor='w'
                         ).pack(side='left')

                var = tk.StringVar(value=str(current[key]))
                rows[key] = var
                entry = tk.Entry(row, textvariable=var, bg=BG_ENTRY, fg=FG,
                                 insertbackground=FG, relief='flat',
                                 font=('Segoe UI', 9), width=12)
                entry.pack(side='left', padx=(0, 8))

                tk.Label(row, text=f'(default: {default})',
                         bg=BG, fg=FG_DIM, font=('Segoe UI', 8)
                         ).pack(side='left')

                tk.Label(inner, text=desc, bg=BG, fg=FG_DIM,
                         font=('Segoe UI', 8), wraplength=480, justify='left'
                         ).pack(anchor='w', padx=(12, 0), pady=(0, 4))

        # Buttons
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(fill='x', padx=16, pady=(0, 12))

        def _save():
            values = {}
            errors = []
            for key, var in rows.items():
                default, type_, label, *_ = settings_mod.DEFAULTS[key]
                raw = var.get().strip()
                if not raw:
                    values[key] = default
                    continue
                try:
                    values[key] = type_(raw)
                except (TypeError, ValueError):
                    errors.append(f'{label}: not a valid {type_.__name__}')
            if errors:
                messagebox.showerror('Invalid input', '\n'.join(errors),
                                     parent=dlg)
                return
            settings_mod.save(values)
            self._log_msg('Settings saved.')
            dlg.destroy()

        def _reset():
            if not messagebox.askyesno(
                    'Reset settings',
                    'Reset all settings to their default values?',
                    parent=dlg):
                return
            settings_mod.reset_to_defaults()
            self._log_msg('Settings reset to defaults.')
            dlg.destroy()
            self._open_settings()

        tk.Button(btn_frame, text='Save', width=10,
                  command=_save,
                  bg=SUCCESS, fg=BG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10, 'bold')
                  ).pack(side='right', padx=(8, 0))
        tk.Button(btn_frame, text='Cancel', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10)
                  ).pack(side='right')
        tk.Button(btn_frame, text='Reset to Defaults', width=18,
                  command=_reset,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10)
                  ).pack(side='left')

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        dlg.bind('<Destroy>',
                 lambda e: canvas.unbind_all('<MouseWheel>')
                 if e.widget == dlg else None)

    # ── Rule editor sub-dialog ───────────────────────────────────────────────

    def _open_rule_editor(self, parent, existing_rule=None, on_save=None,
                          is_new=False):
        """Open a dialog to add or edit a single game-specific rule.

        Args:
            parent:        Parent widget.
            existing_rule: Rule dict to edit (or pre-fill from). None for
                           a blank new rule.
            on_save:       Callback receiving the saved rule dict.
            is_new:        If True, treat existing_rule as starter values
                           for a new rule (changes the dialog title).
        """
        import settings as settings_mod

        dlg = tk.Toplevel(parent)
        if is_new or not existing_rule:
            dlg.title('Add Rule')
        else:
            dlg.title('Edit Rule')
        dlg.geometry('700x860')
        dlg.minsize(640, 600)
        dlg.configure(bg=BG)
        dlg.transient(parent)
        dlg.grab_set()

        existing = existing_rule or {}

        tk.Label(dlg, text='Game Rule', font=('Segoe UI', 13, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(dlg,
                 text='Settings here override the global defaults for ROMs '
                      'whose filename matches the pattern below.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9), wraplength=520,
                 justify='left'
                 ).pack(anchor='w', padx=16)

        # Name + pattern
        meta_frame = tk.Frame(dlg, bg=BG)
        meta_frame.pack(fill='x', padx=16, pady=8)

        tk.Label(meta_frame, text='Name:', bg=BG, fg=FG,
                 font=('Segoe UI', 9), width=10, anchor='e'
                 ).grid(row=0, column=0, sticky='e', pady=2)
        name_var = tk.StringVar(value=existing.get('name', ''))
        tk.Entry(meta_frame, textvariable=name_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 9)
                 ).grid(row=0, column=1, sticky='ew', padx=4, pady=2)

        tk.Label(meta_frame, text='Pattern:', bg=BG, fg=FG,
                 font=('Segoe UI', 9), width=10, anchor='e'
                 ).grid(row=1, column=0, sticky='e', pady=2)
        pattern_var = tk.StringVar(value=existing.get('pattern', ''))
        tk.Entry(meta_frame, textvariable=pattern_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 9)
                 ).grid(row=1, column=1, sticky='ew', padx=4, pady=2)

        regex_var = tk.BooleanVar(value=existing.get('regex', False))
        ttk.Checkbutton(meta_frame, text='Use regular expression',
                        variable=regex_var,
                        style='Jingles.TCheckbutton'
                        ).grid(row=2, column=1, sticky='w', padx=4, pady=2)

        meta_frame.columnconfigure(1, weight=1)

        tk.Label(dlg,
                 text='Pattern is matched against the ROM filename '
                      '(case-insensitive). Substring match by default; '
                      'check the box for regex.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 8),
                 wraplength=600, justify='left'
                 ).pack(anchor='w', padx=16)

        # ── Platforms section ────────────────────────────────────────────
        tk.Label(dlg, text='Platforms',
                 font=('Segoe UI', 11, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=16, pady=(12, 2))
        tk.Label(dlg,
                 text='Restrict this rule to specific platforms. Leave all '
                      'unchecked to apply to any platform.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 8),
                 wraplength=600, justify='left'
                 ).pack(anchor='w', padx=16)

        plat_outer = tk.Frame(dlg, bg=BG_PANEL, height=120)
        plat_outer.pack(fill='x', padx=16, pady=4)
        plat_outer.pack_propagate(False)
        plat_canvas = tk.Canvas(plat_outer, bg=BG_PANEL,
                                highlightthickness=0)
        plat_sb = ttk.Scrollbar(plat_outer, orient='vertical',
                                command=plat_canvas.yview)
        plat_inner = tk.Frame(plat_canvas, bg=BG_PANEL)
        plat_inner.bind(
            '<Configure>',
            lambda e: plat_canvas.configure(
                scrollregion=plat_canvas.bbox('all')))
        plat_canvas.create_window((0, 0), window=plat_inner, anchor='nw')
        plat_canvas.configure(yscrollcommand=plat_sb.set)
        plat_canvas.pack(side='left', fill='both', expand=True)
        plat_sb.pack(side='right', fill='y')

        # Build platform list (unique, sorted)
        unique_platforms = sorted(set(PLATFORM_NAMES.values()))
        existing_platforms = set(existing.get('platforms', []))
        platform_vars = {}  # platform name -> BooleanVar

        # Layout in 3 columns for compactness
        for i, plat in enumerate(unique_platforms):
            var = tk.BooleanVar(value=(plat in existing_platforms))
            platform_vars[plat] = var
            cb = ttk.Checkbutton(plat_inner, text=plat, variable=var,
                                 style='Jingles.TCheckbutton')
            cb.grid(row=i // 3, column=i % 3, sticky='w', padx=8, pady=1)

        # Quick action buttons for platforms
        plat_btns = tk.Frame(dlg, bg=BG)
        plat_btns.pack(fill='x', padx=16, pady=(2, 0))

        def _platforms_clear():
            for v in platform_vars.values():
                v.set(False)

        tk.Button(plat_btns, text='Clear All', command=_platforms_clear,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 8), activebackground='#3A3A5D'
                  ).pack(side='left')

        # Overrides — scrollable list of all settings with checkboxes
        tk.Label(dlg, text='Overrides',
                 font=('Segoe UI', 11, 'bold'),
                 bg=BG, fg=ACCENT
                 ).pack(anchor='w', padx=16, pady=(12, 2))
        tk.Label(dlg,
                 text='Check a setting and enter a value to override it. '
                      'Unchecked settings use the global default.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 8),
                 wraplength=600, justify='left'
                 ).pack(anchor='w', padx=16)

        # Pack the button frame BEFORE the scrollable overrides so it
        # stays anchored to the bottom of the window even when the
        # window is shorter than the natural content height.
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(side='bottom', fill='x', padx=16, pady=(0, 12))

        outer = tk.Frame(dlg, bg=BG)
        outer.pack(fill='both', expand=True, padx=16, pady=4)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        existing_overrides = existing.get('overrides', {})
        override_widgets = {}  # key -> (BooleanVar, StringVar)

        for key, (default, type_, label, desc, group) in \
                settings_mod.DEFAULTS.items():
            row = tk.Frame(inner, bg=BG)
            row.pack(fill='x', pady=1)

            enabled = key in existing_overrides
            enabled_var = tk.BooleanVar(value=enabled)
            value_var = tk.StringVar(
                value=str(existing_overrides.get(key, default)))

            cb = ttk.Checkbutton(row, variable=enabled_var,
                                 style='Jingles.TCheckbutton')
            cb.pack(side='left')

            tk.Label(row, text=label, bg=BG, fg=FG,
                     font=('Segoe UI', 9), width=26, anchor='w'
                     ).pack(side='left')
            tk.Entry(row, textvariable=value_var, bg=BG_ENTRY, fg=FG,
                     insertbackground=FG, relief='flat',
                     font=('Segoe UI', 9), width=12
                     ).pack(side='left', padx=(0, 8))
            tk.Label(row, text=f'({group}, default: {default})',
                     bg=BG, fg=FG_DIM, font=('Segoe UI', 8)
                     ).pack(side='left')

            override_widgets[key] = (enabled_var, value_var)

        def _save():
            name = name_var.get().strip()
            pattern = pattern_var.get().strip()
            if not name:
                messagebox.showerror('Missing name',
                                     'Please enter a name for this rule.',
                                     parent=dlg)
                return
            if not pattern:
                messagebox.showerror('Missing pattern',
                                     'Please enter a pattern.', parent=dlg)
                return

            # Validate regex if enabled
            if regex_var.get():
                try:
                    import re
                    re.compile(pattern)
                except re.error as e:
                    messagebox.showerror('Invalid regex',
                                         f'Pattern is not valid regex:\n{e}',
                                         parent=dlg)
                    return

            overrides = {}
            errors = []
            for key, (enabled_var, value_var) in override_widgets.items():
                if not enabled_var.get():
                    continue
                default, type_, label, *_ = settings_mod.DEFAULTS[key]
                raw = value_var.get().strip()
                try:
                    overrides[key] = type_(raw)
                except (TypeError, ValueError):
                    errors.append(f'{label}: not a valid {type_.__name__}')

            if errors:
                messagebox.showerror('Invalid input',
                                     '\n'.join(errors), parent=dlg)
                return

            selected_platforms = sorted(
                p for p, v in platform_vars.items() if v.get())

            new_rule = {
                'name': name,
                'pattern': pattern,
                'regex': regex_var.get(),
                'platforms': selected_platforms,
                'overrides': overrides,
            }
            if on_save:
                on_save(new_rule)
            dlg.destroy()

        tk.Button(btn_frame, text='Save', width=10,
                  command=_save,
                  bg=SUCCESS, fg=BG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10, 'bold')
                  ).pack(side='right', padx=(8, 0))
        tk.Button(btn_frame, text='Cancel', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10)
                  ).pack(side='right')

    # ── Log ──────────────────────────────────────────────────────────────────

    # ── BIOS Manager ─────────────────────────────────────────────────────────

    def _open_bios_manager(self):
        """Open a dialog to manage BIOS files for systems that require them."""
        from extractors.retroarch import REQUIRED_BIOS, CORE_BIOS
        from extractors.ps2 import find_pcsx2

        dlg = tk.Toplevel(self)
        dlg.title('BIOS Manager')
        dlg.geometry('700x400')
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text='BIOS Files', font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg=ACCENT).pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(dlg, text='Place BIOS files in the expected directories, '
                           'or browse to set custom paths.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(anchor='w', padx=16)

        # Build BIOS entries list
        ra_sys = os.path.join(os.path.dirname(self._retroarch), 'system') \
            if self._retroarch else None
        pcsx2_bios = None
        pcsx2 = find_pcsx2()
        if pcsx2:
            pcsx2_bios = os.path.join(os.path.dirname(pcsx2), 'bios')

        entries = []  # (system_name, expected_files, search_dir, region_label)

        # Extension-based BIOS
        for ext, (filename, system) in REQUIRED_BIOS.items():
            entries.append((system, [filename], ra_sys, ''))

        # Core-based BIOS
        for core, (filenames, system) in CORE_BIOS.items():
            if 'pcsx2' in core:
                search_dir = pcsx2_bios
            else:
                search_dir = ra_sys
            regions = ['USA', 'JPN', 'EUR']
            for i, fname in enumerate(filenames):
                region = regions[i] if i < len(regions) else ''
                entries.append((system, [fname], search_dir, region))

        # Scrollable frame
        canvas = tk.Canvas(dlg, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dlg, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True, padx=(16, 0), pady=8)
        scrollbar.pack(side='right', fill='y', pady=8, padx=(0, 8))

        # Header
        tk.Label(inner, text='System', bg=BG, fg=FG_DIM, font=('Segoe UI', 9, 'bold'),
                 width=20, anchor='w').grid(row=0, column=0, sticky='w', padx=4)
        tk.Label(inner, text='Region', bg=BG, fg=FG_DIM, font=('Segoe UI', 9, 'bold'),
                 width=6, anchor='w').grid(row=0, column=1, sticky='w', padx=4)
        tk.Label(inner, text='File', bg=BG, fg=FG_DIM, font=('Segoe UI', 9, 'bold'),
                 width=30, anchor='w').grid(row=0, column=2, sticky='w', padx=4)
        tk.Label(inner, text='Status', bg=BG, fg=FG_DIM, font=('Segoe UI', 9, 'bold'),
                 width=8, anchor='center').grid(row=0, column=3, padx=4)

        cfg = load_config()
        bios_overrides = cfg.get('bios_overrides', {})

        self._bios_rows = []
        row = 1
        for system, filenames, search_dir, region in entries:
            fname = filenames[0]
            override_key = f'{system}_{region}' if region else system

            # Check if file exists (override or default)
            override_path = bios_overrides.get(override_key, '')
            if override_path and os.path.isfile(override_path):
                found = True
                display = os.path.basename(override_path)
            elif search_dir:
                path = os.path.join(search_dir, fname)
                found = os.path.isfile(path)
                display = fname
            else:
                found = False
                display = fname

            # System name
            tk.Label(inner, text=system, bg=BG, fg=FG,
                     font=('Segoe UI', 9), anchor='w'
                     ).grid(row=row, column=0, sticky='w', padx=4, pady=2)
            # Region
            tk.Label(inner, text=region, bg=BG, fg=FG_DIM,
                     font=('Segoe UI', 9), anchor='w'
                     ).grid(row=row, column=1, sticky='w', padx=4, pady=2)
            # Filename + Browse
            file_frame = tk.Frame(inner, bg=BG)
            file_frame.grid(row=row, column=2, sticky='ew', padx=4, pady=2)
            file_var = tk.StringVar(value=override_path if override_path else display)
            tk.Entry(file_frame, textvariable=file_var, bg=BG_ENTRY, fg=FG,
                     insertbackground=FG, relief='flat', font=('Segoe UI', 9)
                     ).pack(side='left', fill='x', expand=True)
            # Status
            status_lbl = tk.Label(inner, text='Found' if found else 'Missing',
                                  bg=BG, fg=SUCCESS if found else ERROR,
                                  font=('Segoe UI', 9, 'bold'))
            status_lbl.grid(row=row, column=3, padx=4, pady=2)
            tk.Button(file_frame, text='Browse',
                      command=lambda fv=file_var, sl=status_lbl, ok=override_key:
                          self._browse_bios(fv, sl, ok, dlg),
                      bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                      font=('Segoe UI', 9)
                      ).pack(side='left', padx=(4, 0))

            self._bios_rows.append((override_key, file_var, status_lbl, search_dir, fname))
            row += 1

        inner.columnconfigure(2, weight=1)

        # Buttons
        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(fill='x', padx=16, pady=(0, 12))
        tk.Button(btn_frame, text='Save', width=10,
                  command=lambda: self._save_bios(dlg),
                  bg=SUCCESS, fg=BG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10, 'bold')
                  ).pack(side='right', padx=(8, 0))
        tk.Button(btn_frame, text='Close', width=10,
                  command=dlg.destroy,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 10)
                  ).pack(side='right')

    def _browse_bios(self, file_var, status_lbl, override_key, parent):
        """Browse for a BIOS file."""
        path = filedialog.askopenfilename(
            parent=parent,
            title=f'Select BIOS file for {override_key}',
            filetypes=[('BIOS files', '*.bin *.rom'), ('All files', '*.*')])
        if path:
            file_var.set(path)
            if os.path.isfile(path):
                status_lbl.config(text='Found', fg=SUCCESS)
            else:
                status_lbl.config(text='Missing', fg=ERROR)

    def _save_bios(self, dlg):
        """Save BIOS file overrides to config."""
        overrides = {}
        for override_key, file_var, status_lbl, search_dir, default_name in self._bios_rows:
            val = file_var.get().strip()
            # Only save if it's a custom path (not the default filename)
            if val and val != default_name and os.path.isfile(val):
                overrides[override_key] = val
                status_lbl.config(text='Found', fg=SUCCESS)
            elif val and val != default_name:
                status_lbl.config(text='Missing', fg=ERROR)
            else:
                # Check default location
                if search_dir:
                    found = os.path.isfile(os.path.join(search_dir, default_name))
                    status_lbl.config(text='Found' if found else 'Missing',
                                      fg=SUCCESS if found else ERROR)

        save_config(bios_overrides=overrides)
        self._log_msg('BIOS configuration saved.')

    # ── Log ──────────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str):
        self._log.config(state='normal')
        self._log.insert('end', msg + '\n')
        self._log.see('end')
        self._log.config(state='disabled')
