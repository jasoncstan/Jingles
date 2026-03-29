"""Jingles main application window (tkinter)."""
import os
import queue
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from scanner import scan_directory
from utils import (find_ffmpeg, find_7z, find_vgmstream, find_retroarch,
                   get_platform, safe_stem, SUPPORTED_EXTENSIONS,
                   load_config, save_config, OUTPUT_BASE, get_mp3_path,
                   PLATFORM_NAMES)
from worker import ProcessingWorker

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
        self._worker: ProcessingWorker = None
        self._msg_queue           = queue.Queue()
        self._rom_paths: list     = []

        self._input_var     = tk.StringVar()
        self._filter_var    = tk.StringVar()
        self._status_var    = tk.StringVar(value='Ready')
        self._recursive_var = tk.BooleanVar(value=True)
        self._count_var     = tk.StringVar(value='No ROMs loaded')

        # Restore last directories
        cfg = load_config()
        if cfg.get('last_input_dir'):
            self._input_var.set(cfg['last_input_dir'])
        if cfg.get('last_filter_dir'):
            self._filter_var.set(cfg['last_filter_dir'])

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

        self._ffmpeg_lbl = tk.Label(top, font=('Segoe UI', 9), bg=BG_PANEL)
        self._ffmpeg_lbl.pack(side='right', padx=16)
        self._7z_lbl = tk.Label(top, font=('Segoe UI', 9), bg=BG_PANEL)
        self._7z_lbl.pack(side='right', padx=(0, 8))
        self._vgs_lbl = tk.Label(top, font=('Segoe UI', 9), bg=BG_PANEL)
        self._vgs_lbl.pack(side='right', padx=(0, 8))
        self._ra_lbl = tk.Label(top, font=('Segoe UI', 9), bg=BG_PANEL)
        self._ra_lbl.pack(side='right', padx=(0, 8))
        tk.Button(top, text='BIOS…', command=self._open_bios_manager,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).pack(side='right', padx=(0, 8))
        self._refresh_tool_labels()

        # ── Settings row ─────────────────────────────────────────────────────
        cfg_frame = tk.Frame(self, bg=BG, padx=12, pady=8)
        cfg_frame.pack(fill='x')

        # ROM source folder
        tk.Label(cfg_frame, text='ROM Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e'
                 ).grid(row=0, column=0, sticky='e', padx=(0, 6), pady=3)
        tk.Entry(cfg_frame, textvariable=self._input_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 10)
                 ).grid(row=0, column=1, sticky='ew', pady=3)
        tk.Button(cfg_frame, text='Browse…', command=self._browse_input,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).grid(row=0, column=2, padx=(6, 0), pady=3)

        # Filter folder (optional — limits scan to matching names)
        tk.Label(cfg_frame, text='Filter Folder:', bg=BG, fg=FG,
                 font=('Segoe UI', 10), width=14, anchor='e'
                 ).grid(row=1, column=0, sticky='e', padx=(0, 6), pady=3)
        tk.Entry(cfg_frame, textvariable=self._filter_var, bg=BG_ENTRY, fg=FG,
                 insertbackground=FG, relief='flat', font=('Segoe UI', 10)
                 ).grid(row=1, column=1, sticky='ew', pady=3)
        filter_btns = tk.Frame(cfg_frame, bg=BG)
        filter_btns.grid(row=1, column=2, padx=(6, 0), pady=3)
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
                 ).grid(row=2, column=0, sticky='e', padx=(0, 6), pady=3)
        tk.Label(cfg_frame, text=OUTPUT_BASE, bg=BG_ENTRY, fg=FG_DIM,
                 font=('Segoe UI', 9), anchor='w', relief='flat'
                 ).grid(row=2, column=1, sticky='ew', pady=3, ipady=4, ipadx=4)
        tk.Button(cfg_frame, text='Open…', command=self._open_output,
                  bg=BG_ENTRY, fg=FG, relief='flat', cursor='hand2',
                  font=('Segoe UI', 9), activebackground='#3A3A5D'
                  ).grid(row=2, column=2, padx=(6, 0), pady=3)

        # Options row
        opt_row = tk.Frame(cfg_frame, bg=BG)
        opt_row.grid(row=3, column=0, columnspan=3, sticky='w', pady=2)
        ttk.Checkbutton(opt_row, text='Scan subfolders',
                        variable=self._recursive_var,
                        style='Jingles.TCheckbutton').pack(side='left')
        tk.Label(opt_row, textvariable=self._count_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(side='left', padx=16)

        cfg_frame.columnconfigure(1, weight=1)

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

    def _refresh_tool_labels(self):
        self._ffmpeg_lbl.config(
            text='FFmpeg ✓' if self._ffmpeg else 'FFmpeg ✗',
            fg=SUCCESS if self._ffmpeg else WARNING)
        self._7z_lbl.config(
            text='7-Zip ✓' if self._7z else '7-Zip ✗',
            fg=SUCCESS if self._7z else WARNING)
        self._vgs_lbl.config(
            text='vgmstream ✓' if self._vgmstream else 'vgmstream ✗',
            fg=SUCCESS if self._vgmstream else WARNING)

        if self._retroarch:
            from extractors.retroarch import RetroArchExtractor
            ra = RetroArchExtractor(self._retroarch, self._retroarch_cores)
            n = sum(1 for ext in ra.supported_extensions if ra.find_core(ext))
            self._ra_lbl.config(text=f'RetroArch ✓ ({n} cores)', fg=SUCCESS)
        else:
            self._ra_lbl.config(text='RetroArch ✗', fg=WARNING)

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
        folder = self._input_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning('No Folder', 'Please select a valid ROM folder first.')
            return

        filter_dir = self._filter_var.get().strip()
        save_config(last_input_dir=folder,
                    last_filter_dir=filter_dir if filter_dir else None)

        self._tree.delete(*self._tree.get_children())
        self._rom_paths = []
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
            stem     = safe_stem(str(path))
            ext      = os.path.splitext(str(path))[1].lower()
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

        self._worker = ProcessingWorker(
            rom_paths=selected_paths,
            ffmpeg_path=self._ffmpeg,
            seven_zip_path=self._7z,
            vgmstream_path=self._vgmstream,
            retroarch_path=self._retroarch,
            retroarch_cores=self._retroarch_cores,
            msg_queue=self._msg_queue,
        )
        self._worker.start()
        self._log_msg(f'Processing {len(selected_paths)} ROMs → {OUTPUT_BASE}')

    def _on_stop(self):
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

        elif msg_type == 'file_status':
            rom_path, status = data
            tag = {
                'Done':          'done',
                'Already Done':  'exists',
                'Error':         'error',
                'No Audio':      'noaudio',
                'Processing...': 'proc',
                'Pending':       'pending',
            }.get(status, 'pending')
            try:
                vals = self._tree.item(rom_path, 'values')
                old_tags = self._tree.item(rom_path, 'tags')
                # Preserve the 'selected' tag
                new_tags = [tag]
                if 'selected' in old_tags:
                    new_tags.append('selected')
                self._tree.item(rom_path,
                                values=(vals[0], vals[1], vals[2], status),
                                tags=new_tags)
                self._tree.see(rom_path)
            except tk.TclError:
                pass

        elif msg_type == 'log':
            self._log_msg(data)

        elif msg_type == 'done':
            success, failed, skipped, total = data
            self._status_var.set(
                f'Finished: {success} done, {skipped} skipped, {failed} errors')
            self._progress['value'] = 100
            self._start_btn.config(state='normal')
            self._stop_btn.config(state='disabled')
            self._scan_btn.config(state='normal')
            self._log_msg(
                f'--- Finished: {success}/{total} exported, '
                f'{skipped} skipped/no audio, {failed} errors ---')

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
