"""
UX & Window Behavior Service (Act 3):
- Enforces Always-On-Top Z-order via Win32 SetWindowPos so the Island never disappears on click
- Smart Hide in Fullscreen Games (optional, ignores normal desktop apps/browsers)
- Click-Through (Mouse Passthrough via Win32 WS_EX_TRANSPARENT)
- Global Hotkey Polling (Ctrl+Shift+Space for Quick Terminal, Ctrl+Alt+X for Click-through)
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import time
import psutil
from core.state import UXSettings


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

VK_CONTROL = 0x11
VK_MENU = 0x12     # Alt key
VK_SHIFT = 0x10
VK_SPACE = 0x20
VK_X = 0x58

NON_GAME_PROCESSES = {
    "explorer.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "opera.exe",
    "yandex.exe",
    "brave.exe",
    "antigravity.exe",
    "code.exe",
    "idea64.exe",
    "pycharm64.exe",
    "python.exe",
    "pythonw.exe",
    "telegram.exe",
    "discord.exe",
    "applicationframehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "textinputhost.exe",
    "taskmgr.exe",
}


class UXService:
    """Manages Win32 topmost enforcement, click-through, fullscreen game detection, and hotkeys."""

    def __init__(self) -> None:
        self._applied_passthrough: bool = False
        self._last_fs_check: float = 0.0
        self._last_topmost_enforce: float = 0.0
        self._prev_term_hotkey: bool = False
        self._prev_ghost_hotkey: bool = False

    def update(
        self,
        ux: UXSettings,
        island_hwnd: int,
        screen_rect: tuple[int, int, int, int],
        now: float | None = None,
    ) -> tuple[bool, bool]:
        """
        Returns (toggle_terminal_requested, toggle_ghost_requested).
        """
        if now is None:
            now = time.monotonic()

        user32 = ctypes.windll.user32

        # 0. Periodically re-assert HWND_TOPMOST so the Island never disappears behind other windows
        if island_hwnd and now - self._last_topmost_enforce > 0.4:
            self._last_topmost_enforce = now
            try:
                user32.SetWindowPos(
                    wintypes.HWND(island_hwnd),
                    wintypes.HWND(HWND_TOPMOST),
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            except Exception:
                pass

        # 1. Check modifier keys for temporary click-through (Hold Ctrl + Alt)
        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt_down = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        shift_down = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        space_down = bool(user32.GetAsyncKeyState(VK_SPACE) & 0x8000)
        x_down = bool(user32.GetAsyncKeyState(VK_X) & 0x8000)

        ux.is_modifier_held = bool(ux.hold_modifier_passthrough and ctrl_down and alt_down and not x_down)

        # Global Hotkey 1: Ctrl + Shift + Space -> Open/Close Quick Terminal
        term_combo = ctrl_down and shift_down and space_down
        toggle_terminal = term_combo and not self._prev_term_hotkey
        self._prev_term_hotkey = term_combo

        # Global Hotkey 2: Ctrl + Alt + X -> Toggle Click-Through Mode
        ghost_combo = ctrl_down and alt_down and x_down
        toggle_ghost = ghost_combo and not self._prev_ghost_hotkey
        self._prev_ghost_hotkey = ghost_combo

        # 2. Apply or remove WS_EX_TRANSPARENT on island HWND
        want_passthrough = ux.click_through_mode or ux.is_modifier_held
        if want_passthrough != self._applied_passthrough and island_hwnd:
            self._set_window_passthrough(island_hwnd, want_passthrough)
            self._applied_passthrough = want_passthrough

        # 3. Check Fullscreen Smart Hide (only if explicitly enabled by user)
        if ux.smart_hide_fullscreen and now - self._last_fs_check > 1.0:
            self._last_fs_check = now
            ux.is_fullscreen_obscured = self._is_foreground_fullscreen_game(island_hwnd, screen_rect)
        elif not ux.smart_hide_fullscreen:
            ux.is_fullscreen_obscured = False

        return toggle_terminal, toggle_ghost

    @staticmethod
    def _set_window_passthrough(hwnd: int, enable: bool) -> None:
        try:
            user32 = ctypes.windll.user32
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            ex_style = get_long(hwnd, GWL_EXSTYLE)
            if enable:
                new_style = ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                new_style = ex_style & ~WS_EX_TRANSPARENT
            set_long(hwnd, GWL_EXSTYLE, new_style)
        except Exception:
            pass

    @staticmethod
    def _is_foreground_fullscreen_game(
        island_hwnd: int,
        screen_rect: tuple[int, int, int, int],
    ) -> bool:
        try:
            user32 = ctypes.windll.user32
            fg = user32.GetForegroundWindow()
            if not fg or fg == island_hwnd:
                return False

            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(fg, cls_buf, 64)
            if cls_buf.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Qt6120QWindowIcon", "Qt6120QWindowToolSaveBits"):
                return False

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if pid.value:
                try:
                    pname = psutil.Process(pid.value).name().lower()
                    if pname in NON_GAME_PROCESSES:
                        return False
                except Exception:
                    return False

            rect = wintypes.RECT()
            if not user32.GetWindowRect(fg, ctypes.byref(rect)):
                return False

            sx, sy, sw, sh = screen_rect
            win_w = rect.right - rect.left
            win_h = rect.bottom - rect.top

            return (
                rect.left == sx
                and rect.top == sy
                and win_w == sw
                and win_h == sh
            )
        except Exception:
            return False
