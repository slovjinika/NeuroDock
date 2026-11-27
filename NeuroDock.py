import json
import logging
import os
from pathlib import Path
import shlex
import subprocess
import tkinter as tk
from PIL import Image, ImageTk

logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "dock_clicks.json"
BACKUP_FILE = BASE_DIR / "dock_clicks.json.bak"

DEFAULT_APPS = [
    {"name": "Firefox", "cmd": "firefox", "icon_names": ["firefox", "browser"], "clicks": 0},
    {"name": "GIMP", "cmd": "gimp", "icon_names": ["gimp"], "clicks": 0},
    {"name": "Word", "cmd": "libreoffice --writer", "icon_names": ["libreoffice-writer"], "clicks": 0},
    {"name": "Inkscape", "cmd": "inkscape", "icon_names": ["inkscape", "org.inkscape.Inkscape"], "clicks": 0},
    {"name": "Sublime", "cmd": "subl", "icon_names": ["sublime-text", "subl"], "clicks": 0},
    {"name": "Terminal", "cmd": "gnome-terminal", "icon_names": ["utilities-terminal", "terminal"], "clicks": 0},
    {"name": "File Manager", "cmd": "thunar", "icon_names": ["system-file-manager", "thunar", "org.xfce.thunar"], "clicks": 0},
    {"name": "LibreOffice", "cmd": "libreoffice", "icon_names": ["libreoffice-startcenter"], "clicks": 0},
    {"name": "Draw", "cmd": "libreoffice --draw", "icon_names": ["libreoffice-draw"], "clicks": 0},
]


def _parse_valid_clicks(raw_text: str) -> dict[str, int] | None:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    cleaned: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            cleaned[key] = value
    return cleaned


def _write_atomic(target: Path, content: str) -> None:
    tmp_file = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, target)
    except Exception:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
        raise


class AutoHideDock:
    FULL_HEIGHT = 46
    HIDDEN_HEIGHT = 4
    ICON_SIZE = (32, 32)
    HIDE_DELAY_MS = 4000

    def __init__(self, root: tk.Tk, apps: list[dict]):
        self.root = root
        self.apps = [dict(app) for app in apps]
        self.images: dict[str, ImageTk.PhotoImage] = {}
        self.buttons: dict[str, tk.Button] = {}
        self.panel_width = 300
        self.hide_timer_id: str | None = None

        self._setup_window()
        self.load_clicks()
        self.load_icons()
        self._create_buttons_once()
        self.render_dock()
        self.hide_now()

    def _setup_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg="#4a4a4a")

        self.dock_frame = tk.Frame(self.root, bg="#aeb2c3", bd=0)
        self.dock_frame.pack(fill=tk.BOTH, expand=True)

        self.root.bind("<Enter>", self.show_panel)
        self.root.bind("<Leave>", self.schedule_hide)

    def _apply_clicks(self, clicks_map: dict[str, int]) -> None:
        for app in self.apps:
            if app["name"] in clicks_map:
                app["clicks"] = clicks_map[app["name"]]

    def load_clicks(self) -> None:
        for candidate in (DATA_FILE, BACKUP_FILE):
            if not candidate.exists():
                continue
            try:
                parsed = _parse_valid_clicks(candidate.read_text(encoding="utf-8"))
                if parsed is not None:
                    self._apply_clicks(parsed)
                    if candidate == BACKUP_FILE:
                        self.save_clicks(make_backup=False)
                    return
            except Exception as exc:
                logging.warning("Failed to read %s: %s", candidate.name, exc)

    def save_clicks(self, make_backup: bool = True) -> None:
        payload = {app["name"]: app["clicks"] for app in self.apps}
        serialized = json.dumps(payload, ensure_ascii=False, indent=4)

        if make_backup and DATA_FILE.exists():
            try:
                current_text = DATA_FILE.read_text(encoding="utf-8")
                if _parse_valid_clicks(current_text) is not None:
                    _write_atomic(BACKUP_FILE, current_text)
            except Exception as exc:
                logging.warning("Failed to update backup %s: %s", BACKUP_FILE.name, exc)

        try:
            _write_atomic(DATA_FILE, serialized)
        except Exception as exc:
            logging.error("Failed to write %s: %s", DATA_FILE.name, exc)

    @staticmethod
    def find_icon_path(icon_names: list[str]) -> Path | None:
        icon_dirs = (
            Path("/usr/share/icons/Yaru/48x48/apps"),
            Path("/usr/share/icons/Yaru/scalable/apps"),
            Path("/usr/share/icons/hicolor/48x48/apps"),
            Path("/usr/share/icons/hicolor/scalable/apps"),
            Path("/usr/share/pixmaps"),
        )
        extensions = (".png", ".xpm")
        for name in icon_names:
            for directory in icon_dirs:
                for ext in extensions:
                    candidate = directory / f"{name}{ext}"
                    if candidate.is_file():
                        return candidate
        return None

    def load_icons(self) -> None:
        for app in self.apps:
            icon_path = self.find_icon_path(app["icon_names"])
            if icon_path:
                try:
                    with Image.open(icon_path) as raw_img:
                        resized = raw_img.resize(self.ICON_SIZE, Image.Resampling.LANCZOS)
                        self.images[app["name"]] = ImageTk.PhotoImage(resized)
                    continue
                except Exception as exc:
                    logging.warning("Failed to load icon for %s: %s", app["name"], exc)

            fallback = Image.new("RGBA", (16, 16), "#222222")
            self.images[app["name"]] = ImageTk.PhotoImage(fallback)

    def _create_buttons_once(self) -> None:
        for app in self.apps:
            name = app["name"]
            btn = tk.Button(
                self.dock_frame,
                image=self.images.get(name),
                bg="#aeaeae",
                activebackground="#8e8e8e",
                bd=2,
                relief=tk.RAISED,
                command=lambda a=app: self.on_app_click(a),
            )
            btn.bind("<Button-3>", lambda event, a=app: self._show_context_menu(event, a))
            self.buttons[name] = btn

    def render_dock(self) -> None:
        self.apps.sort(key=lambda item: item["clicks"], reverse=True)

        for btn in self.buttons.values():
            btn.pack_forget()

        for app in self.apps:
            self.buttons[app["name"]].pack(side=tk.LEFT, padx=2, pady=2)

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        self.panel_width = min(max(self.dock_frame.winfo_reqwidth() + 12, 120), screen_w)
        x_pos = (screen_w - self.panel_width) // 2
        current_h = max(self.root.winfo_height(), self.HIDDEN_HEIGHT)
        y_pos = self.root.winfo_screenheight() - current_h
        self.root.geometry(f"{self.panel_width}x{current_h}+{x_pos}+{y_pos}")

    def _show_context_menu(self, event: tk.Event, app: dict) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"{app['name']} (clicks: {app['clicks']})", state=tk.DISABLED)
        menu.add_command(label="Reset counter", command=lambda: self.reset_clicks(app))
        menu.add_separator()
        menu.add_command(label="Quit dock", command=self.root.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    def reset_clicks(self, app: dict) -> None:
        app["clicks"] = 0
        self.save_clicks()
        self.render_dock()
        self.show_panel()

    def on_app_click(self, app: dict) -> None:
        app["clicks"] += 1
        self.save_clicks()

        try:
            args = shlex.split(app["cmd"])
            subprocess.Popen(
                args,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            logging.error("Failed to launch %s: %s", app["name"], exc)

        self.render_dock()
        self.show_panel()

    def show_panel(self, _event: tk.Event | None = None) -> None:
        if self.hide_timer_id is not None:
            self.root.after_cancel(self.hide_timer_id)
            self.hide_timer_id = None

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x_pos = (screen_w - self.panel_width) // 2
        y_pos = screen_h - self.FULL_HEIGHT
        self.root.geometry(f"{self.panel_width}x{self.FULL_HEIGHT}+{x_pos}+{y_pos}")

    def schedule_hide(self, _event: tk.Event | None = None) -> None:
        if self.hide_timer_id is not None:
            self.root.after_cancel(self.hide_timer_id)
        self.hide_timer_id = self.root.after(self.HIDE_DELAY_MS, self.hide_now)

    def _is_pointer_inside(self) -> bool:
        px, py = self.root.winfo_pointerxy()
        x1 = self.root.winfo_rootx()
        y1 = self.root.winfo_rooty()
        x2 = x1 + self.root.winfo_width()
        y2 = y1 + self.root.winfo_height()
        return x1 <= px <= x2 and y1 <= py <= y2

    def hide_now(self) -> None:
        self.hide_timer_id = None
        if self._is_pointer_inside():
            self.schedule_hide()
            return

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x_pos = (screen_w - self.panel_width) // 2
        y_pos = screen_h - self.HIDDEN_HEIGHT
        self.root.geometry(f"{self.panel_width}x{self.HIDDEN_HEIGHT}+{x_pos}+{y_pos}")


if __name__ == "__main__":
    tk_root = tk.Tk()
    AutoHideDock(tk_root, DEFAULT_APPS)
    tk_root.mainloop()