import json
import os
import subprocess
import tkinter as tk
from PIL import Image, ImageTk

# Визначаємо шлях до папки, де лежить скрипт, щоб файл data завжди зберігався поруч
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "stopwatchdata")

# Дані додатків
APPS_DATA = [
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

LOADED_IMAGES = {}
CURRENT_PANEL_WIDTH = 300
FULL_HEIGHT = 42
HIDDEN_HEIGHT = 4
hide_timer_id = None


def load_clicks():
    global APPS_DATA
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for app in APPS_DATA:
                    if app["name"] in saved:
                        app["clicks"] = saved[app["name"]]
            print(f"[ІНІЦІАЛІЗАЦІЯ] Дані успішно завантажено з: {DATA_FILE}")
        except Exception as e:
            print(f"[ПОМИЛКА] Помилка читання даних: {e}")
    else:
        print(f"[ІНІЦІАЛІЗАЦІЯ] Файл даних не знайдено. Буде створено новий: {DATA_FILE}")


def save_clicks():
    try:
        data = {app["name"]: app["clicks"] for app in APPS_DATA}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"[УСПІХ] Файл 'data' оновлено! Поточний стан: {data}")
    except Exception as e:
        print(f"[ПОМИЛКА] Помилка запису даних: {e}")


def find_icon_path(icon_names):
    fallback_dirs = [
        "/usr/share/icons/Yaru/48x48/apps/",
        "/usr/share/icons/Yaru/scalable/apps",
        "/usr/share/icons/hicolor/48x48/apps",
        "/usr/share/icons/hicolor/scalable/apps",
        "/usr/share/pixmaps"
    ]
    for name in icon_names:
        for f_dir in fallback_dirs:
            for ext in [".png", ".svg", ".xpm"]:
                path = os.path.join(f_dir, f"{name}{ext}")
                if os.path.exists(path):
                    return path
    return None


def load_icons():
    for app in APPS_DATA:
        icon_path = find_icon_path(app["icon_names"])
        if icon_path:
            try:
                pil_img = Image.open(icon_path).resize((32, 32), Image.Resampling.LANCZOS)
                LOADED_IMAGES[app["name"]] = ImageTk.PhotoImage(pil_img)
                continue
            except Exception as e:
                print(f"Помилка іконки {app['name']}: {e}")
        
        # Заглушка, якщо іконка не знайдена
        blank_img = tk.PhotoImage(width=12, height=12)
        blank_img.put("#000000", to=(0, 0, 12, 12))
        LOADED_IMAGES[app["name"]] = blank_img


def update_dock(show_text=False):
    global APPS_DATA, CURRENT_PANEL_WIDTH
    APPS_DATA = sorted(APPS_DATA, key=lambda x: x["clicks"], reverse=True)
    
    for widget in dock_frame.winfo_children():
        widget.destroy()
        
    for app in APPS_DATA:
        btn_text = f" {app['name'].upper()} [{app['clicks']}] " if show_text else ""
        
        btn = tk.Button(
            dock_frame,
            text=btn_text,
            bg="#aeaeae",
            fg="#000000",
            activebackground="#8e8e8e",
            activeforeground="#000000",
            padx=4,
            pady=2,
            compound=tk.LEFT,
            bd=2,
            relief=tk.RAISED,
            font=("Verdana", 6),
            command=lambda a=app: on_app_click(a)
        )
        
        if app["name"] in LOADED_IMAGES:
            btn.config(image=LOADED_IMAGES[app["name"]])
            
        btn.pack(side=tk.LEFT, padx=2, pady=1)
    
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    CURRENT_PANEL_WIDTH = min(dock_frame.winfo_reqwidth() + 12, screen_width)
    
    x_pos = (screen_width - CURRENT_PANEL_WIDTH) // 2
    root.geometry(f"{CURRENT_PANEL_WIDTH}x{root.winfo_height()}+{x_pos}+{root.winfo_y()}")


def on_app_click(app):
    print(f"\n[КЛИК] Натиснуто на додаток: {app['name']} (кліків до: {app['clicks']})")
    app["clicks"] += 1
    print(f"[КЛИК] Нова кількість кліків для {app['name']}: {app['clicks']}")
    
    save_clicks()  # Зберігаємо та виводимо статус файлу в термінал
    
    try:
        subprocess.Popen(app["cmd"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[ПОМИЛКА] Помилка запуску {app['name']}: {e}")
        
    update_dock()
    show_panel()


def show_panel(event=None):
    global hide_timer_id
    if hide_timer_id is not None:
        root.after_cancel(hide_timer_id)
        hide_timer_id = None
        
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x_pos = (screen_width - CURRENT_PANEL_WIDTH) // 2
    y_pos = screen_height - FULL_HEIGHT
    
    root.geometry(f"{CURRENT_PANEL_WIDTH}x{FULL_HEIGHT}+{x_pos}+{y_pos}")


def hide_panel_delayed(event=None):
    global hide_timer_id
    if hide_timer_id is not None:
        root.after_cancel(hide_timer_id)
    hide_timer_id = root.after(5000, execute_hide)


def execute_hide():
    global hide_timer_id
    hide_timer_id = None
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x_pos = (screen_width - CURRENT_PANEL_WIDTH) // 2
    y_pos = screen_height - HIDDEN_HEIGHT
    
    root.geometry(f"{CURRENT_PANEL_WIDTH}x{HIDDEN_HEIGHT}+{x_pos}+{y_pos}")


# Ініціалізація додатку
root = tk.Tk()
root.overrideredirect(True)
root.wm_attributes("-topmost", True)
root.configure(bg="#4a4a4a")

dock_frame = tk.Frame(root, bg="#aeb2c3", bd=0, relief=tk.SUNKEN)
dock_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

root.bind("<Enter>", show_panel)
root.bind("<Leave>", hide_panel_delayed)

load_clicks()
load_icons()
update_dock()
execute_hide()

root.mainloop()
