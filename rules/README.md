# Pre-built Game Rules

These JSON files contain curated game-specific rules that you can import via **Rules… → Import…** in Jingles.

Each file targets games or series that need different settings than the defaults — typically because they have long publisher logos, lengthy intros, or distinctive title themes that need extra capture time.

## Files

| File | Description |
|---|---|
| [`game_freak.json`](game_freak.json) | Pokemon games across all platforms (Game Boy through 3DS). Game Freak's logo + Pokemon Company logo + boot sequence is one of the longest in games — these rules extend the RetroArch capture window to make sure the title screen audio is reached. |
| [`final_fantasy.json`](final_fantasy.json) | Final Fantasy series and other Square Enix RPGs (Chrono, Kingdom Hearts, Dragon Quest, NieR, etc.). Long Square logos and intro cinematics. |
| [`long_intros.json`](long_intros.json) | A grab-bag of other series with notably long boot sequences: Mega Man, Castlevania, Metal Gear, Sonic, Zelda, Mario, Kirby, Metroid, EarthBound, Fire Emblem, Resident Evil, Street Fighter, and more. |

## How to import

1. Open Jingles
2. Click **Rules…** in the top bar
3. Click **Import…**
4. Select one of the JSON files from this folder
5. When prompted, choose **Yes (Merge)** to add them to your existing rules without overwriting anything

You can import multiple files — duplicates by name are automatically renamed with a numeric suffix (e.g. `Pokemon (DS) (2)`) so nothing is lost.

## What the rules do

Most rules tweak two settings:

- **`retroarch_capture_frames`** — how many emulation frames to record before stopping. The defaults are 480 (8 s) for GBA, 1200 (20 s) for DS, etc. Long-intro games need more.
- **`clip_max_secs`** — the maximum length of the final MP3 clip. Default is 6 s; some title themes are longer and need 8–12 s to feel complete.

PS2 rules also tweak:

- **`ps2_turbo_boot_secs`** — how long PCSX2 stays in turbo mode to skip past logos
- **`ps2_record_secs`** — how long to record after the game settles

All rules are platform-scoped, so a "Pokemon (GBA)" rule only fires for `.gba` files in the Game Boy Advance platform — it won't accidentally affect a different Pokemon game on a different system.

## Editing rules after import

Once imported, you can freely edit, delete, or reorder rules in the **Rules…** dialog. Imports just add to your local config — the original JSON files in this folder are never read again at runtime.

## Contributing rules

If you find a game or series that consistently needs different settings, you can:

1. Create a rule for it via **Rules… → + Add Rule**
2. Test that it works for your library
3. Use **Export…** to save your rules to a JSON file
4. Open a PR adding it (or new entries to an existing file) to this folder
