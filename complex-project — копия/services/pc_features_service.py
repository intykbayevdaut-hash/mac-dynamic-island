"""
PC-Specific Services (Real Windows Integrations):
- Real Active Browser Download Monitor (tracks actual byte growth, ignores stale .crdownload files)
- Real File Shelf & Drag-and-Drop Actions (Copy actual file to Windows clipboard for Ctrl+V, Drag-Out, .ZIP, Recycle Bin)
- Quick Terminal / Run Prompt (Math calculator, App launcher, Web search, Shell command runner)
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import subprocess
import time
import webbrowser
import zipfile

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QGuiApplication

from core.state import (
    DownloadInfo,
    DropZoneInfo,
    NotificationInfo,
    ShelfFileItem,
    TerminalInfo,
)


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


class PCFeaturesService:
    """Handles Real Downloads, File Shelf, Drag-and-Drop File Actions, and Quick Terminal."""

    MAX_SHELF_FILES = 4

    def __init__(self) -> None:
        self._last_tick = time.monotonic()
        self._downloads_dir = Path.home() / "Downloads"
        self._last_dir_check = 0.0
        # Map of partial file path -> last observed byte size
        self._partial_file_sizes: dict[str, int] = {}
        self._is_demo_download: bool = False
        self._snapshot_existing_partials()

    def _snapshot_existing_partials(self) -> None:
        """Record existing stale .crdownload/.part files at startup so they never false-trigger."""
        if not self._downloads_dir.exists():
            return
        try:
            for entry in self._downloads_dir.iterdir():
                if entry.suffix.lower() in (".crdownload", ".part", ".opdownload"):
                    try:
                        self._partial_file_sizes[str(entry)] = entry.stat().st_size
                    except OSError:
                        pass
        except Exception:
            pass

    def seed_shelf_files(self, drop_info: DropZoneInfo, project_dir: Path) -> None:
        for fname in ("README.md", "run.bat"):
            fpath = project_dir / fname
            if fpath.exists():
                self.add_to_shelf(drop_info, str(fpath))

    # ------------------------------------------------------------------
    # 1. Real File Downloads & Transfer Progress
    # ------------------------------------------------------------------
    def start_download_demo(
        self,
        dl: DownloadInfo,
        filename: str = "Windows11_DynamicIsland_Pack.zip",
        speed_mbps: float = 54.8,
    ) -> None:
        self._is_demo_download = True
        dl.active = True
        dl.filename = filename
        dl.progress = 0.02
        dl.speed_mbps = speed_mbps
        self._last_tick = time.monotonic()

    def stop_download(self, dl: DownloadInfo) -> None:
        self._is_demo_download = False
        dl.active = False
        dl.alert_until = 0.0

    def update_downloads(self, dl: DownloadInfo, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        dt = min(0.1, max(0.001, now - self._last_tick))
        self._last_tick = now

        # Check ~/Downloads every 1.5s ONLY for files whose size is actively growing right now
        if not self._is_demo_download and now - self._last_dir_check > 1.5:
            elapsed_poll = max(0.5, now - self._last_dir_check)
            self._last_dir_check = now
            self._check_real_active_downloads(dl, elapsed_poll, now)

        if self._is_demo_download and dl.active:
            dl.progress += dt * 0.22
            dl.speed_mbps = round(48.0 + 12.0 * math.sin(now * 3.0), 1)
            if dl.progress >= 1.0:
                dl.progress = 1.0
                dl.active = False
                self._is_demo_download = False
                dl.alert_until = now + 2.0

    def _check_real_active_downloads(self, dl: DownloadInfo, elapsed: float, now: float) -> None:
        if not self._downloads_dir.exists():
            return
        found_growing = False
        try:
            current_paths: set[str] = set()
            for entry in self._downloads_dir.iterdir():
                if entry.suffix.lower() in (".crdownload", ".part", ".opdownload"):
                    full_str = str(entry)
                    current_paths.add(full_str)
                    try:
                        st = entry.stat()
                    except OSError:
                        continue

                    prev_size = self._partial_file_sizes.get(full_str)
                    self._partial_file_sizes[full_str] = st.st_size

                    # Only trigger if the file was modified in the last 3 seconds AND grew in size
                    if prev_size is not None and st.st_size > prev_size and (time.time() - st.st_mtime) < 3.5:
                        delta_mb = (st.st_size - prev_size) / (1024 * 1024)
                        dl.active = True
                        dl.filename = entry.stem
                        dl.speed_mbps = round(max(0.1, delta_mb / elapsed), 1)
                        dl.progress = min(0.95, (dl.progress + 0.08) if dl.active else 0.15)
                        found_growing = True
                        break

            # Clean up finished partial files
            for old_path in list(self._partial_file_sizes.keys()):
                if old_path not in current_paths:
                    del self._partial_file_sizes[old_path]
                    if dl.active and not self._is_demo_download:
                        dl.progress = 1.0
                        dl.active = False
                        dl.alert_until = now + 2.2

            if not found_growing and dl.active and not self._is_demo_download:
                dl.active = False
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2. Drag-and-Drop Zone, File Shelf & Real Clipboard File Copy
    # ------------------------------------------------------------------
    def add_to_shelf(self, drop_info: DropZoneInfo, file_path: str) -> ShelfFileItem:
        p = Path(file_path)
        abs_str = str(p.resolve()) if p.exists() else str(p)
        ext = (p.suffix.lstrip(".").upper() or "FILE")[:4]
        size_str = self._format_path_size(p)

        drop_info.shelf_files = [f for f in drop_info.shelf_files if f.path != abs_str]
        item = ShelfFileItem(path=abs_str, name=p.name, ext_badge=ext, size_str=size_str)
        drop_info.shelf_files.insert(0, item)
        if len(drop_info.shelf_files) > self.MAX_SHELF_FILES:
            drop_info.shelf_files = drop_info.shelf_files[: self.MAX_SHELF_FILES]
        return item

    def copy_file_to_windows_clipboard(self, file_path: str) -> bool:
        """Copies the actual file object to Windows Clipboard so user can press Ctrl+V in Telegram/Explorer."""
        if not file_path or not os.path.exists(file_path):
            return False
        cb = QGuiApplication.clipboard()
        if cb is None:
            return False
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(os.path.abspath(file_path))])
        cb.setMimeData(mime)
        return True

    def reveal_in_explorer(self, file_path: str) -> None:
        if file_path and os.path.exists(file_path):
            try:
                subprocess.Popen(f'explorer /select,"{os.path.abspath(file_path)}"', shell=True)
            except Exception:
                pass

    def clear_shelf(self, drop_info: DropZoneInfo) -> None:
        drop_info.shelf_files.clear()

    @staticmethod
    def _format_path_size(p: Path) -> str:
        try:
            if p.is_file():
                size_kb = p.stat().st_size / 1024.0
                if size_kb > 1024:
                    return f"{size_kb / 1024.0:.1f} МБ"
                return f"{max(1, int(size_kb))} КБ"
            if p.is_dir():
                return "Папка"
        except Exception:
            pass
        return "Файл"

    def accept_dropped_file(self, drop_info: DropZoneInfo, file_path: str) -> None:
        p = Path(file_path)
        drop_info.dragging_over = False
        drop_info.dropped_file_path = str(p)
        drop_info.dropped_file_name = p.name
        drop_info.dropped_file_size_str = self._format_path_size(p)
        self.add_to_shelf(drop_info, file_path)
        self.copy_file_to_windows_clipboard(file_path)
        drop_info.status_feedback = "✅ Файл на Полке и скопирован (можно нажать Ctrl+V в любом окне)!"

    def archive_dropped_file(self, drop_info: DropZoneInfo) -> str:
        src = Path(drop_info.dropped_file_path)
        if not src.exists():
            drop_info.status_feedback = "⚠️ Файл не найден"
            return drop_info.status_feedback

        zip_path = src.with_suffix(src.suffix + ".zip")
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if src.is_file():
                    zf.write(src, arcname=src.name)
                else:
                    for root, _, files in os.walk(src):
                        for f in files:
                            full = Path(root) / f
                            zf.write(full, arcname=str(full.relative_to(src.parent)))
            self.add_to_shelf(drop_info, str(zip_path))
            self.copy_file_to_windows_clipboard(str(zip_path))
            drop_info.status_feedback = f"✅ Создан и скопирован в буфер: {zip_path.name} (жми Ctrl+V)"
        except Exception as e:
            drop_info.status_feedback = f"⚠️ Ошибка архивации: {e}"
        return drop_info.status_feedback

    def send_to_recycle_bin(self, drop_info: DropZoneInfo) -> bool:
        path = drop_info.dropped_file_path
        if not path or not os.path.exists(path):
            drop_info.status_feedback = "⚠️ Файл уже удален или не существует"
            return False
        abs_p = os.path.abspath(path)
        project_root = str(Path(__file__).resolve().parent.parent)
        if abs_p.startswith(project_root) and not abs_p.endswith("demo_drop_file.txt"):
            drop_info.status_feedback = "🛡️ Системный файл проекта защищен от удаления!"
            return False
        try:
            op = _SHFILEOPSTRUCTW()
            op.hwnd = 0
            op.wFunc = FO_DELETE
            op.pFrom = os.path.abspath(path) + "\0\0"
            op.pTo = None
            op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            if res == 0:
                drop_info.shelf_files = [f for f in drop_info.shelf_files if f.path != os.path.abspath(path)]
                drop_info.status_feedback = "🗑️ Перемещено в Корзину Windows!"
                return True
        except Exception:
            pass
        drop_info.status_feedback = "⚠️ Не удалось переместить в Корзину"
        return False

    # ------------------------------------------------------------------
    # 3. Quick Terminal / Run Prompt
    # ------------------------------------------------------------------
    def execute_terminal_command(self, term: TerminalInfo, raw_cmd: str) -> str:
        cmd = raw_cmd.strip()
        if not cmd:
            term.last_output = "Введите выражение (например 1024*8) или команду (calc, ipconfig)"
            return term.last_output

        if cmd.startswith("?"):
            q = cmd[1:].strip()
            if q:
                webbrowser.open(f"https://www.google.com/search?q={q}")
                term.last_output = f"🌐 Открыт поиск в браузере: {q}"
                return term.last_output

        allowed_math = {
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "pi": math.pi,
            "pow": pow,
            "abs": abs,
            "round": round,
        }
        if any(op in cmd for op in ("+", "-", "*", "/", "**", "sqrt", "pi")) and not cmd.startswith(
            ("cmd", "dir", "echo", "ipconfig", "ping")
        ):
            try:
                val = eval(cmd, {"__builtins__": {}}, allowed_math)
                if isinstance(val, (int, float)):
                    term.last_output = f"🧮 Ответ: {val} (скопировано в буфер!)"
                    cb = QGuiApplication.clipboard()
                    if cb:
                        cb.setText(str(val))
                    return term.last_output
            except Exception:
                pass

        lower = cmd.lower()
        gui_apps = {
            "calc": "calc.exe",
            "notepad": "notepad.exe",
            "explorer": "explorer.exe",
            "mspaint": "mspaint.exe",
            "taskmgr": "taskmgr.exe",
            "cmd": "cmd.exe",
        }
        if lower in gui_apps:
            try:
                subprocess.Popen(gui_apps[lower], shell=True)
                term.last_output = f"🚀 Запущено: {gui_apps[lower]}"
                return term.last_output
            except Exception as e:
                term.last_output = f"⚠️ Ошибка: {e}"
                return term.last_output

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=2.5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            if lines:
                term.last_output = f"❯ {lines[0][:68]}"
            else:
                term.last_output = f"✅ Выполнено (код {proc.returncode})"
        except Exception as e:
            term.last_output = f"⚠️ Ошибка выполнения: {e}"

        return term.last_output

    # ------------------------------------------------------------------
    # 4. Incoming Custom Notifications
    # ------------------------------------------------------------------
    def trigger_notification(
        self,
        notif: NotificationInfo,
        app_name: str,
        sender: str,
        message: str,
    ) -> None:
        presets = {
            "Telegram": ("TG", (56, 189, 248)),
            "Discord": ("DS", (129, 140, 248)),
            "Почта": ("✉️", (251, 191, 36)),
            "GitHub": ("GH", (52, 211, 153)),
        }
        badge, color = presets.get(app_name, ("🔔", (168, 85, 247)))
        notif.app_name = app_name
        notif.app_badge = badge
        notif.accent_color = color
        notif.sender = sender
        notif.message = message
        notif.alert_until = time.monotonic() + 4.2
