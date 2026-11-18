# 🧠 NeuroDock

**NeuroDock** is a lightweight, self-organizing floating panel for Linux built with Python and Tkinter. Moving away from static docks, NeuroDock monitors your daily workflow and **dynamically reorganizes your applications** based on usage frequency (click count)—putting your most essential tools right where you need them.

Featuring a smooth autohide mechanism, it tucks away quietly at the bottom of the screen and expands instantly whenever you hover over it.

---

## ✨ Key Capabilities

* **🧬 Adaptive Sorting:** Applications automatically shift positions based on how often you launch them.
* **💾 Local Persistence:** Click counts are securely saved locally (`stopwatchdata`), ensuring your custom layout is remembered across reboots.
* **👁️ Smart Autohide:** Collapses into a minimalist strip and restores seamlessly on mouse hover (`<Enter>` / `<Leave>`).
* **🖼️ System Icon Scanner:** Automatically looks up and scales high-quality icons from standard Linux theme paths (`Yaru`, `hicolor`, `pixmaps`).
* **📌 Borderless & Topmost:** Floats effortlessly above other windows without standard OS window decorations.

---

## 🛠️ Built With

* **Python 3**
* **Tkinter** (GUI framework)
* **Pillow (`PIL`)** (Image processing & resizing)
* **JSON / Subprocess** (Data management & process execution)

---

## 📦 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/slovjinika/NeuroDock.git
cd NeuroDock

```

### 2. Install dependencies

Ensure you have Python 3 and the Pillow library installed:

```bash
pip install Pillow

```

### 3. Launch the application

```bash
python3 main.py

```

---

## ⚙️ Customization

You can easily tailor the app list to your workflow by modifying the `APPS_DATA` array in the script. Each item includes the display name, shell execution command, fallback icon names, and click counter:

```python
APPS_DATA = [
    {"name": "Firefox", "cmd": "firefox", "icon_names": ["firefox", "browser"], "clicks": 0},
    {"name": "GIMP", "cmd": "gimp", "icon_names": ["gimp"], "clicks": 0},
    # Add your own custom commands and icon fallbacks here...
]

```

---

## 📄 License

Distributed under the MIT License. Feel free to use, fork, and adapt it to your needs.
