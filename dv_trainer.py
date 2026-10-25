"""Dragon View (Steam release) trainer: god mode, unlimited MP / jade / bombs / potions / fruit, add EXP.

The Steam release runs the SNES ROM inside a bundled Mednafen (bSNES v059) core,
so every cheat works on the emulated machine rather than on the wrapper:

  * WRAM ($7E0000-$7FFFFF) is bSNES's global StaticRAM `wram` (128 KiB).
  * The ROM is bSNES's global MappedRAM `cartrom`. Patching it is how the known
    Game Genie codes work: each one turns the STA that writes a reduced counter
    back to RAM into an LDA, so the counter simply never goes down.

Both globals are {vtable, data*, size} structs in the exe image, so they are
found by scanning the image for that shape. Run with pythonw; closing the
window restores the ROM, which turns every cheat off.
"""

import ctypes
import ctypes.wintypes as wt
import re
import struct
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

EXE = "dragon view.exe"

# WRAM offsets (bank $7E)
HP, HP_MAX = 0x6FCA, 0x6FCB
MP, MP_MAX = 0x6FCD, 0x6FCE
JADE = 0x2131  # 16-bit
BOMBS = 0x2103
POTIONS = 0x2109
FRUIT = 0x2111  # 8-bit; spent on upgrades
LEVEL = 0x7094
EXP = 0x7095  # 32-bit progress toward the next level; a level-up subtracts that level's threshold
EXP_GAINED = 0xE7B3  # set to $FF when EXP is granted, so the HUD runs the level-up check
SAVE_TAG = 0x2138  # copy of the save block's signature; present once a game is loaded
SAVE_TAG_VALUE = b"S-DRAKKHEN"

JADE_MAX = 9999  # the game's own cap
FRUIT_FILL = 250  # pickups INC fruit with no cap check, so 255 would wrap to 0 on the next one
LEVEL_NO_EXP = 0x2E  # the game stops granting EXP from this level on
EXP_DIGITS = 7
ROM_TITLE = b"DRAGON VIEW"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]

PROCESS_ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400  # VM_OPERATION | VM_READ | VM_WRITE | QUERY_INFORMATION
TH32CS_SNAPPROCESS, TH32CS_SNAPMODULE, TH32CS_SNAPMODULE32 = 0x2, 0x8, 0x10
STILL_ACTIVE = 259
INVALID_HANDLE = wt.HANDLE(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE), ("szModule", wt.WCHAR * 256),
                ("szExePath", wt.WCHAR * 260)]


def find_pid(name: str) -> Optional[int]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE:
        return None
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name:
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


def find_module(pid: int, name: str) -> Optional[tuple[int, int]]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE:
        return None
    try:
        entry = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
        ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == name:
                return entry.modBaseAddr, entry.modBaseSize
            ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


class Process:
    def __init__(self, pid: int):
        self.pid = pid
        self.handle = kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
        if not self.handle:
            raise OSError(f"can't open the game process (error {ctypes.get_last_error()})")

    def read(self, addr: int, size: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.handle, addr, buf, size, ctypes.byref(got)) or got.value != size:
            return None
        return buf.raw

    def write(self, addr: int, data: bytes) -> None:
        done = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(self.handle, addr, data, len(data), ctypes.byref(done)) \
                or done.value != len(data):
            raise OSError(f"write to {addr:#x} failed (error {ctypes.get_last_error()})")

    def alive(self) -> bool:
        code = wt.DWORD()
        return bool(kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))) and code.value == STILL_ACTIVE

    def close(self) -> None:
        kernel32.CloseHandle(self.handle)


def lorom_offset(snes_addr: int) -> int:
    return ((snes_addr >> 16) & 0x7F) * 0x8000 + (snes_addr & 0x7FFF)


class Game:
    """The emulated SNES inside a running Dragon View process."""

    def __init__(self, proc: Process):
        self.proc = proc
        module = find_module(proc.pid, EXE)
        if not module:
            raise OSError("can't find the game's exe module")
        self.wram, self.rom = self._locate(*module)

    def _locate(self, base: int, size: int) -> tuple[int, int]:
        image = bytearray(size)
        for off in range(0, size, 0x1000):
            page = self.proc.read(base + off, 0x1000)
            if page:
                image[off:off + 0x1000] = page

        # Every {vtable, data*, size} triple whose vtable points back into the image.
        words = memoryview(image).cast("I")
        end = base + size
        triples = [(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)
                   if base <= words[i] < end and words[i + 1]]

        # wram shares its vtable with the other StaticRAMs: apuram/vram (64K), oam (544), cgram (512).
        sizes_by_vtable: dict[int, set[int]] = {}
        for vtable, _, n in triples:
            sizes_by_vtable.setdefault(vtable, set()).add(n)
        wram = next((data for vtable, data, n in triples
                     if n == 0x20000 and {0x10000, 544, 512} <= sizes_by_vtable[vtable]
                     and self.proc.read(data, 0x20000)), None)

        rom = next((data for vtable, data, n in triples
                    if 0x100000 <= n <= 0x800000 and self.proc.read(data + 0x7FC0, len(ROM_TITLE)) == ROM_TITLE),
                   None)

        if wram is None or rom is None:
            raise OSError("game is still starting up (emulator memory not found yet)")
        return wram, rom

    def alive(self) -> bool:
        return self.proc.alive()

    def r8(self, off: int) -> int:
        data = self.proc.read(self.wram + off, 1)
        if data is None:
            raise OSError("lost access to game memory")
        return data[0]

    def r16(self, off: int) -> int:
        data = self.proc.read(self.wram + off, 2)
        if data is None:
            raise OSError("lost access to game memory")
        return struct.unpack("<H", data)[0]

    def r32(self, off: int) -> int:
        data = self.proc.read(self.wram + off, 4)
        if data is None:
            raise OSError("lost access to game memory")
        return struct.unpack("<I", data)[0]

    def w8(self, off: int, value: int) -> None:
        self.proc.write(self.wram + off, bytes([value]))

    def w16(self, off: int, value: int) -> None:
        self.proc.write(self.wram + off, struct.pack("<H", value))

    def w32(self, off: int, value: int) -> None:
        self.proc.write(self.wram + off, struct.pack("<I", value))

    def in_game(self) -> bool:
        return self.proc.read(self.wram + SAVE_TAG, len(SAVE_TAG_VALUE)) == SAVE_TAG_VALUE

    def rom_byte(self, snes_addr: int) -> int:
        data = self.proc.read(self.rom + lorom_offset(snes_addr), 1)
        if data is None:
            raise OSError("lost access to game memory")
        return data[0]

    def set_rom_byte(self, snes_addr: int, value: int) -> None:
        self.proc.write(self.rom + lorom_offset(snes_addr), bytes([value]))


@dataclass
class Cheat:
    label: str
    store_at: tuple[int, ...]  # SNES addresses of the STAs that write the reduced value back
    store_op: int  # their opcode: $8F (STA long) or $8D (STA abs); LDA is the same opcode | $20
    hold: Optional[Callable[[Game], None]] = None  # extra RAM write each tick while in a game

    def sync(self, game: Game, enabled: bool) -> None:
        want = self.store_op | 0x20 if enabled else self.store_op
        have = [game.rom_byte(addr) for addr in self.store_at]
        for addr, byte in zip(self.store_at, have):
            if byte not in (self.store_op, self.store_op | 0x20):
                raise OSError(f"unexpected ROM byte {byte:02X} at ${addr:06X}; different game version?")
        for addr, byte in zip(self.store_at, have):
            if byte != want:
                game.set_rom_byte(addr, want)


def top_up(cur: int, cap: int) -> Callable[[Game], None]:
    def hold(game: Game) -> None:
        top = game.r8(cap)
        if game.r8(cur) < top:
            game.w8(cur, top)
    return hold


def max_jade(game: Game) -> None:
    if game.r16(JADE) != JADE_MAX:
        game.w16(JADE, JADE_MAX)


# Store sites come from the Game Genie codes CE65-4586, C237-4116, CE34-3106, CE23-C9A2 and CE26-41A3.
# Fruit has no code; its sites are every STA $7E2111 that lowers it: the two upgrade payments
# ($92F232, $92F294), selling fruit ($92E629) and eating one to heal ($93D9B4).
CHEATS = [
    Cheat("God mode (HP never drops)", (0x9E807E,), 0x8F, top_up(HP, HP_MAX)),
    Cheat("Unlimited MP", (0x9AE039,), 0x8D, top_up(MP, MP_MAX)),
    Cheat("Unlimited jade (9999)", (0x92E329,), 0x8F, max_jade),
    Cheat("Unlimited bombs", (0x93D6E7,), 0x8F),
    Cheat("Unlimited potions", (0x93D88B,), 0x8F),
    Cheat("Unlimited fruit (upgrades are free)", (0x92F232, 0x92F294, 0x92E629, 0x93D9B4), 0x8F),
]

TICK_MS = 100
ATTACH_EVERY = 10  # ticks between attach attempts


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.game: Optional[Game] = None
        self.ticks = 0

        root.title("Dragon View Trainer")
        root.resizable(False, False)
        frame = tk.Frame(root, padx=14, pady=12)
        frame.pack()

        self.status = tk.Label(frame, text="Looking for Dragon View...", anchor="w", width=46)
        self.status.pack(fill="x")
        self.stats = tk.Label(frame, text="", anchor="w", font=("Consolas", 10))
        self.stats.pack(fill="x", pady=(4, 10))

        self.vars = []
        for cheat in CHEATS:
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(frame, text=cheat.label, variable=var, anchor="w").pack(fill="x")
            self.vars.append(var)

        tk.Button(frame, text=f"Fill fruit to {FRUIT_FILL}", command=self.fill_fruit).pack(anchor="w", pady=(8, 0))

        exp_row = tk.Frame(frame)
        exp_row.pack(anchor="w", pady=(8, 0))
        digits_only = (root.register(lambda text: re.fullmatch(f"[0-9]{{0,{EXP_DIGITS}}}", text) is not None), "%P")
        self.exp_entry = tk.Entry(exp_row, width=10, validate="key", validatecommand=digits_only)
        self.exp_entry.pack(side="left")
        self.exp_entry.bind("<Return>", lambda _: self.add_exp())
        tk.Button(exp_row, text="Add EXP", command=self.add_exp).pack(side="left", padx=(6, 0))

        tk.Label(frame, text="Bombs/potions/fruit stop decreasing; you still need\n"
                             "one bomb or potion, or enough fruit for the upgrade.\n"
                             "Closing this window turns every cheat off.",
                 anchor="w", justify="left", fg="gray40").pack(fill="x", pady=(10, 0))

        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.tick()

    def attach(self) -> None:
        pid = find_pid(EXE)
        if pid is None:
            self.status.config(text="Waiting for Dragon View to start...")
            return
        proc = Process(pid)
        try:
            self.game = Game(proc)
        except OSError:
            proc.close()
            raise
        self.status.config(text=f"Attached to Dragon View (pid {pid})")

    def detach(self) -> None:
        if self.game:
            self.game.proc.close()
        self.game = None

    def tick(self) -> None:
        try:
            if self.game and not self.game.alive():
                self.detach()
                self.stats.config(text="")
            if self.game is None and self.ticks % ATTACH_EVERY == 0:
                self.attach()
            if self.game:
                self.apply()
        except OSError as e:
            self.detach()
            self.status.config(text=f"Not attached: {e}")
        self.ticks += 1
        self.root.after(TICK_MS, self.tick)

    def apply(self) -> None:
        game = self.game
        in_game = game.in_game()
        for cheat, var in zip(CHEATS, self.vars):
            cheat.sync(game, var.get())
            if var.get() and cheat.hold and in_game:
                cheat.hold(game)
        if in_game:
            self.stats.config(text=f"Lv {game.r8(LEVEL)}   EXP {game.r32(EXP):,}\n"
                                   f"HP {game.r8(HP)}/{game.r8(HP_MAX)}   MP {game.r8(MP)}/{game.r8(MP_MAX)}   "
                                   f"Jade {game.r16(JADE)}\nBombs {game.r8(BOMBS)}   Potions {game.r8(POTIONS)}   "
                                   f"Fruit {game.r8(FRUIT)}")
        else:
            self.stats.config(text="No save loaded yet")

    def in_save(self, action: str) -> Optional[Game]:
        if self.game and self.game.in_game():
            return self.game
        self.status.config(text=f"Load a save first, then {action}")
        return None

    def fill_fruit(self) -> None:
        try:
            if game := self.in_save("fill fruit"):
                game.w8(FRUIT, FRUIT_FILL)
        except OSError as e:
            self.detach()
            self.status.config(text=f"Not attached: {e}")

    def add_exp(self) -> None:
        amount = int(self.exp_entry.get() or 0)
        if amount == 0:
            self.status.config(text="Type how much EXP to add first")
            return
        try:
            if game := self.in_save("add EXP"):
                if game.r8(LEVEL) >= LEVEL_NO_EXP:
                    self.status.config(text="Already at max level")
                    return
                # Same as a kill: bump EXP, then flag it so the game levels up on its own.
                game.w32(EXP, game.r32(EXP) + amount)
                game.w8(EXP_GAINED, 0xFF)
                self.status.config(text=f"Added {amount:,} EXP")
        except OSError as e:
            self.detach()
            self.status.config(text=f"Not attached: {e}")

    def quit(self) -> None:
        if self.game and self.game.alive():
            for cheat in CHEATS:
                try:
                    cheat.sync(self.game, False)
                except OSError:
                    pass
        self.detach()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
