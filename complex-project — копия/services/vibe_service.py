"""
Act 5: Vibe Coder & Everyday Super-Pack Service.
Features:
1. Real Localhost Dev Port Radar (psutil.net_connections) + 1-Click Open in Browser + 1-Click Kill Process
   + Built-in Live Test Server on localhost:8080.
2. AI Vibe-Coding Prompt Vault (1-click copy high-leverage prompts + save custom prompt from clipboard).
3. Live 60 FPS Screen Pixel Eyedropper (samples screen color under cursor & copies #HEX to clipboard).
4. 1-Click Instant Screenshot to Windows Clipboard (Ctrl+V image) AND File Shelf (.png file drag-out).
"""

from __future__ import annotations
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import threading
import time
import webbrowser

import psutil
from PyQt6.QtGui import QCursor, QGuiApplication

from core.state import (
    ClipboardAlertInfo,
    DevPortItem,
    DropZoneInfo,
    PetCompanionInfo,
    PromptChip,
    VibeStudioInfo,
)
from services.clipboard_service import ClipboardService
from services.pc_features_service import PCFeaturesService


WATCHED_DEV_PORTS = {
    3000, 3001, 3002, 4000, 4200, 4321,
    5000, 5173, 5174, 5500, 7860,
    8000, 8008, 8080, 8081, 8501, 8888,
    9000, 11434,
}

DEV_PROCESS_KEYWORDS = (
    "node", "python", "bun", "deno", "vite", "next",
    "uvicorn", "gunicorn", "flask", "django", "go",
    "cargo", "ruby", "php", "java", "ollama", "docker",
)


class _DemoVibeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Dynamic Island Vibe Server :8080</title>"
            "<style>body{background:#07090f;color:#f8fafc;font-family:'Segoe UI',sans-serif;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}"
            ".card{background:#121726;border:1px solid #38bdf8;border-radius:20px;padding:36px;"
            "text-align:center;box-shadow:0 0 40px rgba(56,189,248,0.25);}"
            "h1{color:#38bdf8;margin-top:0;}p{color:#cbd5e1;font-size:17px;}</style></head>"
            "<body><div class='card'><h1>⚡ Dynamic Island Pro — Localhost :8080</h1>"
            "<p>Тестовый dev-сервер для вайбкодинга успешно работает!</p>"
            "<p>Вы можете закрыть этот порт прямо из Dynamic Island кнопкой <b>💀 Kill</b>.</p>"
            "</div></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, format: str, *args) -> None:
        pass


class VibeService:
    """Provides Vibe Coder & Everyday User tools for the Dynamic Island."""

    def __init__(self, assets_dir: Path | None = None) -> None:
        if assets_dir is None:
            assets_dir = Path(__file__).resolve().parent.parent / "assets"
        self.assets_dir = assets_dir
        self.shots_dir = self.assets_dir / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)

        self._last_port_scan: float = 0.0
        self._was_eyedropper_active: bool = False
        self._demo_httpd: HTTPServer | None = None
        self._demo_thread: threading.Thread | None = None

    def init_state(self, vibe: VibeStudioInfo) -> None:
        if not vibe.prompts:
            vibe.prompts = [
                PromptChip(
                    label="✨ Дизайн Шик",
                    prompt_text=(
                        "Сделай ультра-современный премиальный дизайн (Liquid Glass, плавные анимации, "
                        "идеальные отступы, продуманная темная палитра) и проверь отсутствие багов."
                    ),
                ),
                PromptChip(
                    label="🐛 Глубокий Фикс",
                    prompt_text=(
                        "Найди первопричину ошибки (root cause), исправь её без костылей, "
                        "проверь все крайние случаи и запусти автотест для подтверждения."
                    ),
                ),
                PromptChip(
                    label="⚡ Чистый Код",
                    prompt_text=(
                        "Отрефактори код: модульная архитектура, строгая типизация, "
                        "высокая производительность, сохрани 100% текущей функциональности."
                    ),
                ),
                PromptChip(
                    label="🚀 Полный Стек",
                    prompt_text=(
                        "Реализуй фичу целиком от бэкенда и состояния до интерактивного UI, "
                        "чтобы всё работало в реальности без заглушек."
                    ),
                ),
            ]
        self.scan_dev_ports(vibe)

    def update(
        self,
        vibe: VibeStudioInfo,
        clipboard_service: ClipboardService,
        now: float | None = None,
        scan_ports: bool = False,
    ) -> None:
        if now is None:
            now = time.monotonic()

        # 1. Live 60 FPS Screen Eyedropper sampling
        if now < vibe.eyedropper_active_until:
            self._was_eyedropper_active = True
            self._sample_cursor_pixel(vibe)
        elif self._was_eyedropper_active:
            # Eyedropper just finished: lock & copy #HEX to clipboard + history!
            self._was_eyedropper_active = False
            clipboard_service.process_copied_text(vibe.eyedropper_hex, now)
            vibe.status_message = f"💧 Цвет {vibe.eyedropper_hex} скопирован в буфер обмена (Ctrl+V)!"
            vibe.status_until = now + 3.5

        # 2. Periodic Dev Port Radar scan every 3.5s only when Vibe tab is open
        if scan_ports and (now - self._last_port_scan > 3.5):
            self._last_port_scan = now
            self.scan_dev_ports(vibe)

    def _sample_cursor_pixel(self, vibe: VibeStudioInfo) -> None:
        try:
            pos = QCursor.pos()
            vibe.eyedropper_pos = (pos.x(), pos.y())
            screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
            if screen is None:
                return
            geom = screen.geometry()
            local_x = pos.x() - geom.x()
            local_y = pos.y() - geom.y()
            pix = screen.grabWindow(0, local_x, local_y, 1, 1)
            img = pix.toImage()
            if not img.isNull():
                col = img.pixelColor(0, 0)
                r, g, b = col.red(), col.green(), col.blue()
                vibe.eyedropper_rgb = (r, g, b)
                vibe.eyedropper_hex = f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            pass

    def start_eyedropper(self, vibe: VibeStudioInfo, duration: float = 3.5) -> None:
        self._sample_cursor_pixel(vibe)
        vibe.eyedropper_active_until = time.monotonic() + duration

    def capture_screen_to_shelf_and_clipboard(
        self,
        vibe: VibeStudioInfo,
        drop_info: DropZoneInfo,
        cb_info: ClipboardAlertInfo,
        pc_service: PCFeaturesService | None = None,
    ) -> str:
        """Captures full screen to PNG on File Shelf AND puts image in Windows Clipboard."""
        if pc_service is None:
            pc_service = PCFeaturesService()
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return ""
        try:
            pix = screen.grabWindow(0)
            ts = datetime.now().strftime("%H%M%S")
            fpath = self.shots_dir / f"Screenshot_{ts}.png"
            pix.save(str(fpath), "PNG")

            # 1. Put image in Windows Clipboard for immediate Ctrl+V in Telegram/Discord/Docs
            cb = QGuiApplication.clipboard()
            if cb is not None:
                cb.setPixmap(pix)

            # 2. Add file to Island File Shelf for Drag-Out
            pc_service.add_to_shelf(drop_info, str(fpath))

            now = time.monotonic()
            vibe.status_message = f"📸 Скриншот в буфере (Ctrl+V) и на Полке: {fpath.name}"
            vibe.status_until = now + 4.0
            cb_info.copied_feedback_text = f"📸 Скриншот {fpath.name} готов к вставке (Ctrl+V)!"
            cb_info.copied_feedback_until = now + 3.0
            return str(fpath)
        except Exception as e:
            vibe.status_message = f"⚠️ Ошибка скриншота: {e}"
            vibe.status_until = time.monotonic() + 3.0
            return ""

    def copy_prompt(
        self,
        vibe: VibeStudioInfo,
        index: int,
        clipboard_service: ClipboardService,
    ) -> None:
        if 0 <= index < len(vibe.prompts):
            chip = vibe.prompts[index]
            clipboard_service.copy_text_silently(chip.prompt_text)
            vibe.status_message = f"🤖 Промпт «{chip.label}» скопирован! Жмите Ctrl+V в чате ИИ"
            vibe.status_until = time.monotonic() + 3.2

    def save_clipboard_as_prompt(self, vibe: VibeStudioInfo) -> None:
        cb = QGuiApplication.clipboard()
        if cb is None:
            return
        txt = (cb.text() or "").strip()
        if not txt:
            vibe.status_message = "⚠️ В буфере обмена нет текста для сохранения"
            vibe.status_until = time.monotonic() + 2.5
            return
        short_words = " ".join(txt.split()[:2])[:14]
        label = f"⭐ {short_words}"
        vibe.prompts.insert(0, PromptChip(label=label, prompt_text=txt))
        vibe.prompts = vibe.prompts[:4]
        vibe.status_message = f"✅ Сохранен ваш промпт: «{label}»"
        vibe.status_until = time.monotonic() + 3.0

    # ------------------------------------------------------------------
    # Dev Port Radar & Built-in Demo Server (:8080)
    # ------------------------------------------------------------------
    def scan_dev_ports(self, vibe: VibeStudioInfo) -> list[DevPortItem]:
        found: dict[int, DevPortItem] = {}

        # Always include our built-in demo server if active
        if self._demo_httpd is not None:
            found[8080] = DevPortItem(port=8080, pid=os.getpid(), process_name="vibe-server")

        try:
            conns = psutil.net_connections(kind="inet")
            for c in conns:
                if c.status != psutil.CONN_LISTEN or not c.laddr:
                    continue
                port = int(c.laddr.port)
                if port in found:
                    continue
                pid = c.pid or 0
                pname = ""
                if pid > 0:
                    try:
                        pname = psutil.Process(pid).name().replace(".exe", "")
                    except Exception:
                        pname = "server"
                is_watched_port = port in WATCHED_DEV_PORTS
                is_dev_proc = (
                    2000 <= port <= 12000
                    and any(k in pname.lower() for k in DEV_PROCESS_KEYWORDS)
                )
                if is_watched_port or is_dev_proc:
                    found[port] = DevPortItem(
                        port=port,
                        pid=pid,
                        process_name=pname or "localhost",
                    )
        except Exception:
            pass

        vibe.active_ports = sorted(found.values(), key=lambda x: x.port)[:3]
        return vibe.active_ports

    def toggle_demo_server(self, vibe: VibeStudioInfo) -> bool:
        """Starts or stops a real local HTTP server on 127.0.0.1:8080 for testing Port Radar."""
        if self._demo_httpd is not None:
            self.stop_demo_server()
            vibe.status_message = "🛑 Тестовый сервер :8080 остановлен"
            vibe.status_until = time.monotonic() + 2.5
            self.scan_dev_ports(vibe)
            return False

        for candidate_port in (8080, 3000, 5173, 8000):
            try:
                httpd = HTTPServer(("127.0.0.1", candidate_port), _DemoVibeHandler)
                self._demo_httpd = httpd
                self._demo_thread = threading.Thread(
                    target=httpd.serve_forever, daemon=True
                )
                self._demo_thread.start()
                vibe.status_message = f"🚀 Запущен живой сервер http://localhost:{candidate_port}!"
                vibe.status_until = time.monotonic() + 3.5
                self.scan_dev_ports(vibe)
                return True
            except OSError:
                continue

        vibe.status_message = "⚠️ Не удалось занять порт для демо-сервера"
        vibe.status_until = time.monotonic() + 2.5
        return False

    def stop_demo_server(self) -> None:
        if self._demo_httpd is not None:
            try:
                self._demo_httpd.shutdown()
                self._demo_httpd.server_close()
            except Exception:
                pass
            self._demo_httpd = None
            self._demo_thread = None

    def open_port_in_browser(self, vibe: VibeStudioInfo, port: int) -> None:
        url = f"http://localhost:{port}"
        webbrowser.open(url)
        vibe.status_message = f"🌐 Открыто в браузере: {url}"
        vibe.status_until = time.monotonic() + 2.5

    def kill_port(self, vibe: VibeStudioInfo, index: int) -> None:
        if not (0 <= index < len(vibe.active_ports)):
            return
        item = vibe.active_ports[index]
        # Don't kill our own Dynamic Island process if it's the built-in demo server!
        if item.pid == os.getpid() or self._demo_httpd is not None and item.port in (8080, 3000, 5173, 8000):
            self.stop_demo_server()
            vibe.status_message = f"💀 Порт :{item.port} ({item.process_name}) освобожден!"
            vibe.status_until = time.monotonic() + 3.0
            self.scan_dev_ports(vibe)
            return

        if item.pid > 0:
            try:
                proc = psutil.Process(item.pid)
                proc.terminate()
                vibe.status_message = f"💀 Процесс {item.process_name} (:{item.port}) завершен!"
                vibe.status_until = time.monotonic() + 3.0
            except Exception as e:
                vibe.status_message = f"⚠️ Не удалось закрыть :{item.port}: {e}"
                vibe.status_until = time.monotonic() + 3.0
        self.scan_dev_ports(vibe)

    # ------------------------------------------------------------------
    # Act 6: AI Context Bundler, Quick App Launcher & Pet Companion
    # ------------------------------------------------------------------
    def bundle_context_for_ai(
        self,
        vibe: VibeStudioInfo,
        drop_info: DropZoneInfo,
        cb_info: ClipboardAlertInfo,
        clipboard_service: ClipboardService,
    ) -> str:
        """Bundles files from the File Shelf into a clean Markdown block for AI chats and copies to Clipboard."""
        paths: list[Path] = []
        for sfile in drop_info.shelf_files:
            p = Path(sfile.path)
            if p.exists() and p.is_file():
                paths.append(p)

        if not paths:
            root = Path(__file__).resolve().parent.parent
            for fallback_rel in ("main.py", "core/state.py"):
                fp = root / fallback_rel
                if fp.exists():
                    paths.append(fp)

        sections: list[str] = [
            f"# 📦 Контекст проекта для ИИ ({len(paths)} файл(ов))",
            "Ниже приведены актуальные файлы проекта для анализа и доработки:\n",
        ]
        bundled_names: list[str] = []
        for idx, p in enumerate(paths[:4], start=1):
            ext = p.suffix.lstrip(".").lower() or "txt"
            bundled_names.append(p.name)
            try:
                if ext in ("png", "jpg", "jpeg", "gif", "wav", "mp3", "zip", "exe"):
                    body = f"[Бинарный/медиа файл: {p.name}, размер {p.stat().st_size} байт]"
                else:
                    raw_text = p.read_text(encoding="utf-8", errors="replace")
                    lines = raw_text.splitlines()
                    if len(lines) > 160:
                        body = "\n".join(lines[:160]) + f"\n\n# ... (еще {len(lines) - 160} строк) ..."
                    else:
                        body = raw_text
            except Exception as e:
                body = f"[Ошибка чтения {p.name}: {e}]"

            sections.append(f"## {idx}. `{p.name}` (`{p}`)\n```{ext}\n{body}\n```\n")

        markdown_bundle = "\n".join(sections)
        now = time.monotonic()
        clipboard_service.copy_text_silently(markdown_bundle)
        clipboard_service._push_history(
            "text",
            markdown_bundle,
            f"📦 Контекст ИИ ({', '.join(bundled_names)[:22]})",
            (168, 85, 247),
        )
        msg = f"📦 Склеено {len(bundled_names)} файл(а) в Markdown! Жмите Ctrl+V в чате ИИ"
        vibe.status_message = msg
        vibe.status_until = now + 4.0
        cb_info.copied_feedback_text = msg
        cb_info.copied_feedback_until = now + 4.0
        cb_info.kind = "text"
        cb_info.preview_text = f"📦 AI Bundle: {', '.join(bundled_names)}"
        cb_info.char_count = len(markdown_bundle)
        return markdown_bundle

    def launch_quick_app(self, app_key: str, vibe: VibeStudioInfo) -> None:
        """1-Click Quick App & Web Launcher for everyday users and vibe coders."""
        import subprocess

        now = time.monotonic()
        try:
            if app_key == "youtube":
                webbrowser.open("https://www.youtube.com")
                vibe.status_message = "🚀 Открыт YouTube в браузере"
            elif app_key == "telegram":
                tg_path = Path(os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"))
                if tg_path.exists():
                    subprocess.Popen([str(tg_path)])
                    vibe.status_message = "🚀 Запущен Telegram Desktop"
                else:
                    webbrowser.open("https://web.telegram.org")
                    vibe.status_message = "🚀 Открыт Telegram Web"
            elif app_key == "discord":
                webbrowser.open("https://discord.com/app")
                vibe.status_message = "🚀 Открыт Discord"
            elif app_key == "ai_chat":
                webbrowser.open("https://chatgpt.com")
                vibe.status_message = "🤖 Открыт ИИ-чат в браузере"
            elif app_key == "github":
                webbrowser.open("https://github.com")
                vibe.status_message = "🐙 Открыт GitHub"
            elif app_key == "downloads":
                dl_dir = Path.home() / "Downloads"
                os.startfile(str(dl_dir if dl_dir.exists() else Path.home()))
                vibe.status_message = "📂 Открыта папка Загрузки"
            elif app_key == "vscode":
                subprocess.Popen("code", shell=True)
                vibe.status_message = "💻 Запущен VS Code"
            elif app_key == "calc":
                subprocess.Popen("calc.exe", shell=True)
                vibe.status_message = "🧮 Запущен Калькулятор Windows"
        except Exception:
            pass
        vibe.status_until = now + 3.0

    def pet_interact(self, pet: PetCompanionInfo, vibe: VibeStudioInfo, cycle: bool = False) -> None:
        """Pets/feeds the Island Companion (+15 XP) or switches pet species."""
        now = time.monotonic()
        if cycle:
            new_name = pet.cycle_species()
            pet.happy_until = now + 3.2
            pet.speech_bubble = f"Привет! Я {new_name}! ✨"
            pet.speech_until = now + 3.2
            vibe.status_message = f"🐾 Ваш питомец на острове: {new_name} (Ур. {pet.level})"
            vibe.status_until = now + 3.2
            return

        pet.xp += 20
        leveled_up = False
        if pet.xp >= 100:
            pet.level += 1
            pet.xp -= 100
            leveled_up = True

        pet.happy_until = now + 3.2
        if leveled_up:
            pet.speech_bubble = f"🎉 УРОВЕНЬ {pet.level}! Люблю тебя! ♥"
        else:
            phrases = {
                "cat": f"Мур-мяу! ♥ +20 XP (Ур.{pet.level})",
                "bot": f"Бип-буп! ⚡ +20 XP (Ур.{pet.level})",
                "fox": f"Фыр-фыр! 🔥 +20 XP (Ур.{pet.level})",
            }
            pet.speech_bubble = phrases.get(pet.species, "♥ +20 XP!")
        pet.speech_until = now + 3.2
        vibe.status_message = f"🐾 {pet.name}: {pet.speech_bubble}"
        vibe.status_until = now + 3.2
