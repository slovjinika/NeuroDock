#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

FULL_HEIGHT = 46
HIDDEN_HEIGHT = 4
ICON_SIZE = 32
HIDE_DELAY_MS = 4000


DEFAULT_APPS = [
    {"name": "Firefox", "cmd": "firefox", "icon_names": ["firefox", "browser"]},
    {"name": "GIMP", "cmd": "gimp", "icon_names": ["gimp"]},
    {"name": "Word", "cmd": "libreoffice --writer", "icon_names": ["libreoffice-writer"]},
    {"name": "Inkscape", "cmd": "inkscape", "icon_names": ["inkscape", "org.inkscape.Inkscape"]},
    {"name": "Sublime", "cmd": "subl", "icon_names": ["sublime-text", "subl"]},
    {"name": "Terminal", "cmd": "gnome-terminal", "icon_names": ["utilities-terminal", "terminal"]},
    {
        "name": "File Manager",
        "cmd": "thunar",
        "icon_names": ["system-file-manager", "thunar", "org.xfce.thunar"],
    },
    {"name": "LibreOffice", "cmd": "libreoffice", "icon_names": ["libreoffice-startcenter"]},
    {"name": "Draw", "cmd": "libreoffice --draw", "icon_names": ["libreoffice-draw"]},
]


def write_atomic_file(target_path: Path, content: str) -> bool:
    tmp_path = target_path.with_name(f"{target_path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
        return True
    except OSError as exc:
        GLib.log_structured(
            "NeuroDock",
            GLib.LogLevelFlags.LEVEL_WARNING,
            {"MESSAGE": f"Failed to write {target_path}: {exc}"},
        )
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return False


def parse_clicks_json(raw_json: str) -> dict[str, int] | None:
    if not raw_json or not raw_json.strip():
        return None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    result: dict[str, int] = {}
    for key, val in data.items():
        if isinstance(key, str) and isinstance(val, int) and not isinstance(val, bool):
            if 0 <= val <= 2**31 - 1:
                result[key] = val
    return result


def create_app_icon_widget(icon_names: list[str]) -> Gtk.Image:
    theme = Gtk.IconTheme.get_default()
    for name in icon_names:
        try:
            pixbuf = theme.load_icon(name, ICON_SIZE, Gtk.IconLookupFlags.FORCE_SIZE)
            if pixbuf is not None:
                return Gtk.Image.new_from_pixbuf(pixbuf)
        except GLib.Error:
            pass

    fallback_dirs = [
        Path("/usr/share/icons/Yaru/48x48/apps"),
        Path("/usr/share/icons/hicolor/48x48/apps"),
        Path("/usr/share/pixmaps"),
    ]
    exts = [".png", ".xpm"]

    for name in icon_names:
        for base_dir in fallback_dirs:
            for ext in exts:
                path = base_dir / f"{name}{ext}"
                if path.is_file():
                    try:
                        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                            str(path), ICON_SIZE, ICON_SIZE, True
                        )
                        if pb is not None:
                            return Gtk.Image.new_from_pixbuf(pb)
                    except GLib.Error:
                        pass

    return Gtk.Image.new_from_icon_name(
        "application-x-executable", Gtk.IconSize.LARGE_TOOLBAR
    )


class DockApp:
    def __init__(self, script_dir: Path):
        self.data_path = script_dir / "dock_clicks.json"
        self.backup_path = script_dir / "dock_clicks.json.bak"
        self.panel_width = 300
        self.is_hidden = True
        self.hide_timer_id = 0

        self.apps = [
            {
                "name": item["name"],
                "cmd": item["cmd"],
                "icon_names": item["icon_names"],
                "clicks": 0,
            }
            for item in DEFAULT_APPS
        ]
        self.load_clicks()

        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self._setup_css()

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.box.set_border_width(2)
        self.window.add(self.box)

        self.window.connect("enter-notify-event", self.on_enter_notify)
        self.window.connect("leave-notify-event", self.on_leave_notify)
        self.window.connect("map-event", self.on_map_event)
        self.window.connect("destroy", Gtk.main_quit)

        self.rebuild_dock_ui()
        self.window.show_all()
        self.apply_panel_state(True)

    def _setup_css(self) -> None:
        provider = Gtk.CssProvider()
        css = b"""
        window.dock-strip {
          background-color: #dddddd;
          border-radius: 3px 3px 0 0;
          min-height: 0;
          min-width: 0;
          padding: 0;
          margin: 0;
        }
        """
        provider.load_from_data(css)
        ctx = self.window.get_style_context()
        ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def build_clicks_json(self) -> str:
        payload = {app["name"]: app["clicks"] for app in self.apps}
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def save_clicks(self, make_backup: bool) -> None:
        serialized = self.build_clicks_json()
        if make_backup and self.data_path.is_file():
            try:
                current = self.data_path.read_text(encoding="utf-8")
                if parse_clicks_json(current) is not None:
                    write_atomic_file(self.backup_path, current)
            except OSError:
                pass
        write_atomic_file(self.data_path, serialized)

    def load_clicks(self) -> None:
        for idx, path in enumerate([self.data_path, self.backup_path]):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parsed = parse_clicks_json(content)
            if parsed is not None:
                for app in self.apps:
                    if app["name"] in parsed:
                        app["clicks"] = parsed[app["name"]]
                if idx == 1:
                    self.save_clicks(make_backup=False)
                return

    def apply_panel_state(self, hidden: bool) -> None:
        self.is_hidden = hidden
        height = HIDDEN_HEIGHT if hidden else FULL_HEIGHT
        width = (
            max(140, self.panel_width // 2) if hidden else self.panel_width
        )

        ctx = self.window.get_style_context()
        if hidden:
            self.box.hide()
            ctx.add_class("dock-strip")
        else:
            ctx.remove_class("dock-strip")
            self.box.show()

        display = self.window.get_display()
        monitor = display.get_primary_monitor() if display else None
        if monitor is None and display and display.get_n_monitors() > 0:
            monitor = display.get_monitor(0)

        geom = Gdk.Rectangle()
        if monitor is not None:
            geom = monitor.get_geometry()
        if geom.width <= 0:
            geom.width = 1920
        if geom.height <= 0:
            geom.height = 1080

        if width > geom.width:
            width = geom.width
        x = geom.x + (geom.width - width) // 2
        y = geom.y + geom.height - height

        self.window.set_size_request(width, height)
        self.window.resize(width, height)
        self.window.move(x, y)

        gdk_win = self.window.get_window()
        if gdk_win is not None:
            gdk_win.move_resize(x, y, width, height)
            gdk_win.raise_()

    def on_map_event(self, _widget, _event) -> bool:
        self.apply_panel_state(self.is_hidden)
        return False

    def hide_panel_cb(self) -> bool:
        self.hide_timer_id = 0

        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display else None
        pointer = seat.get_pointer() if seat else None

        if pointer is not None:
            _, px, py = pointer.get_position()
            wx, wy = self.window.get_position()
            ww, wh = self.window.get_size()
            if wx <= px <= wx + ww and wy <= py <= wy + wh:
                self.hide_timer_id = GLib.timeout_add(HIDE_DELAY_MS, self.hide_panel_cb)
                return GLib.SOURCE_REMOVE

        self.apply_panel_state(True)
        return GLib.SOURCE_REMOVE

    def show_panel_now(self) -> None:
        if self.hide_timer_id > 0:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = 0
        self.apply_panel_state(False)

    def on_enter_notify(self, _widget, _event) -> bool:
        self.show_panel_now()
        return False

    def on_leave_notify(self, _widget, _event) -> bool:
        if self.hide_timer_id > 0:
            GLib.source_remove(self.hide_timer_id)
        self.hide_timer_id = GLib.timeout_add(HIDE_DELAY_MS, self.hide_panel_cb)
        return False

    def launch_detached(self, cmd: str) -> None:
        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            GLib.log_structured(
                "NeuroDock",
                GLib.LogLevelFlags.LEVEL_WARNING,
                {"MESSAGE": f"Failed to parse command '{cmd}': {exc}"},
            )
            return

        if not argv:
            return

        try:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            GLib.log_structured(
                "NeuroDock",
                GLib.LogLevelFlags.LEVEL_WARNING,
                {"MESSAGE": f"Failed to launch '{cmd}': {exc}"},
            )

    def on_reset_clicks(self, _item, app: dict) -> None:
        app["clicks"] = 0
        self.save_clicks(make_backup=True)
        self.rebuild_dock_ui()
        self.show_panel_now()

    def on_quit_dock(self, _item) -> None:
        Gtk.main_quit()

    def on_button_press(self, _widget, event: Gdk.EventButton, app: dict) -> bool:
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            menu = Gtk.Menu()

            info_item = Gtk.MenuItem.new_with_label(f"{app['name']} (clicks: {app['clicks']})")
            info_item.set_sensitive(False)
            menu.append(info_item)

            reset_item = Gtk.MenuItem.new_with_label("Reset counter")
            reset_item.connect("activate", self.on_reset_clicks, app)
            menu.append(reset_item)

            sep = Gtk.SeparatorMenuItem()
            menu.append(sep)

            quit_item = Gtk.MenuItem.new_with_label("Quit dock")
            quit_item.connect("activate", self.on_quit_dock)
            menu.append(quit_item)

            menu.show_all()
            menu.popup_at_pointer(event)
            return True

        return False

    def on_app_clicked(self, _button, app: dict) -> None:
        app["clicks"] += 1
        self.save_clicks(make_backup=True)
        self.launch_detached(app["cmd"])
        self.rebuild_dock_ui()
        self.show_panel_now()

    def rebuild_dock_ui(self) -> None:
        self.apps.sort(key=lambda a: (-a["clicks"], a["name"]))

        for child in self.box.get_children():
            self.box.remove(child)
            child.destroy()

        for app in self.apps:
            btn = Gtk.Button()
            icon = create_app_icon_widget(app["icon_names"])
            btn.add(icon)
            btn.set_tooltip_text(app["name"])

            btn.connect("clicked", self.on_app_clicked, app)
            btn.connect("button-press-event", self.on_button_press, app)

            self.box.pack_start(btn, False, False, 2)

        self.box.show_all()
        _, nat_req = self.box.get_preferred_size()
        self.panel_width = max(120, nat_req.width + 16)


def main() -> int:
    Gtk.init([])
    script_dir = Path(__file__).resolve().parent
    DockApp(script_dir)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())