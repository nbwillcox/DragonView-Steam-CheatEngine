# Dragon View (Steam) Cheat Engine

A free, open-source trainer for the Steam release of **Dragon View**, the 1994 SNES action RPG. It's a single small Python file with no dependencies, so you can read every line before you run it.

![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

| Cheat | What it does |
|---|---|
| God mode | HP never drops, and is topped back up to max |
| Unlimited MP | Ring magic costs nothing, and MP stays full |
| Unlimited jade | Jade holds at 9999 (the game's own cap) and spending doesn't lower it |
| Unlimited bombs / potions | Using one doesn't lower the count |
| Unlimited fruit | Upgrades, selling and eating don't use up fruit |
| Fill fruit | Sets fruit to 250 |
| Add EXP | Adds any amount of EXP; the game then levels you up the normal way |

There's also a live readout of your level, EXP, HP, MP, jade, bombs, potions and fruit.

## Usage

1. Install [Python 3.9+](https://www.python.org/downloads/) for Windows. The standard installer includes tkinter, which is the only thing needed.
2. Download this repo (or just `dv_trainer.py` and `Dragon View Trainer.bat`).
3. Double-click **`Dragon View Trainer.bat`**, or run `pythonw dv_trainer.py`.
4. Start Dragon View from Steam, either before or after the trainer, and load a save.
5. Tick the cheats you want.

Closing the trainer window turns every cheat off.

## How it works

The Steam release runs the original SNES ROM inside a bundled [Mednafen](https://mednafen.github.io/) (bSNES v059) core. Because of that, the trainer works on the emulated SNES rather than on the game wrapper.

- **Finding memory.** bSNES keeps the SNES work RAM (`wram`) and the cartridge ROM (`cartrom`) in global `{vtable, data*, size}` objects inside the exe. The trainer scans the exe image for that shape. No hard-coded process addresses are used, so it survives ASLR and restarts.
- **"Unlimited" cheats.** These patch the in-memory ROM the same way a Game Genie does. The `STA` instruction that writes a reduced value back to RAM becomes an `LDA`, so the counter simply never goes down. The ROM file on disk is never touched, and turning a cheat off restores the original byte.
- **Value cheats.** Holding HP, MP or jade, filling fruit, and adding EXP are plain writes to work RAM.
- **Add EXP.** It sets the same "EXP gained" flag the game sets after a kill, so the game runs its own level-up logic, including stat gains and the animation.

### RAM map (bank `$7E`)

| Address | Size | Meaning |
|---|---|---|
| `$7E6FCA` / `$7E6FCB` | 8-bit | HP / max HP |
| `$7E6FCD` / `$7E6FCE` | 8-bit | MP / max MP |
| `$7E2131` | 16-bit | Jade (cap 9999) |
| `$7E2103` | 8-bit | Bombs |
| `$7E2109` | 8-bit | Potions |
| `$7E2111` | 8-bit | Fruit |
| `$7E7094` | 8-bit | Level |
| `$7E7095` | 32-bit | EXP toward the next level |
| `$7EE7B3` | 8-bit | "EXP gained" flag (`$FF` triggers the level-up check) |

The ROM patch sites are listed in `CHEATS` in [`dv_trainer.py`](dv_trainer.py). Most come from the known Game Genie codes. The fruit sites were found by tracing every write to `$7E2111`.

## Notes

- **Fruit is one byte, so 255 is the hard maximum.** Fruit pickups add 1 with no cap check, so 255 would wrap to 0 on the next pickup. That's why the fill button stops at 250.
- **Unlimited bombs, potions and fruit** stop the count from going down. You still need at least one bomb or potion, or enough fruit to afford the upgrade.
- **Max level.** The game stops granting EXP at level 46, so Add EXP does nothing there.
- **Version.** Tested on the current Steam build. If a different build's ROM doesn't match, the trainer shows "unexpected ROM byte" and patches nothing.
- **Antivirus.** Like any trainer, it reads and writes another process's memory, so some antivirus tools may flag it. Being plain readable source makes it easy to verify.

This is a single-player game. Please don't use this to mislead anyone about legitimate runs.

## Contributing

Bug reports, test results and new cheats are welcome. Open an issue or a pull request. It's especially useful to say which Steam build you tested on and whether each cheat worked.

## License

[MIT](LICENSE). Free to use, change and share.

*Dragon View is a trademark of its respective owners. This project is not affiliated with or endorsed by them, and it includes no game files.*
