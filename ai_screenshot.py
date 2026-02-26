import sys
import os
import io
import base64
import logging
import threading
import json
import time
import ctypes
import tkinter as tk
from tkinter import messagebox, simpledialog
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageTk

# Lazy imports placeholder
mss = None
requests = None
pystray = None
winreg = None

# ─── DPI Awareness ──────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass

# ─── Логирование ────────────────────────────────────────────────
APP_DATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "ScreenAI"
APP_DATA.mkdir(parents=True, exist_ok=True)

LOG_DIR = APP_DATA / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")]
)
logger = logging.getLogger("ScreenAI")

# ─── Конфиг ─────────────────────────────────────────────────────
# Try load from user data first, then local (installer)
load_dotenv(APP_DATA / ".env")
load_dotenv() 

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MODELS = {
    "gpt-5.2": "GPT-5.2 (Superior)",
    "gpt-4o": "GPT-4o (Smart)",
    "gpt-4o-mini": "GPT-4o Mini (Fast)"
}
MAX_IMAGE_SIZE = (1600, 900)
JPEG_QUALITY = 85
HISTORY_FILE = APP_DATA / "history.json"

SYSTEM_PROMPT = (
    "Тебе дан скриншот с вопросом (тестом или задачей). "
    "Напиши ТОЛЬКО текст правильного варианта ответа. "
    "ЗАПРЕЩЕНО: объяснения, рассуждения, LaTeX (никаких `\\(` или `\\frac`). "
    "Всю математику пиши в одну строку обычным текстом (например: `1 / (4 - a)` или `x^2`)."
)

def get_mss():
    global mss
    if mss is None: import mss
    return mss

def get_requests():
    global requests
    if requests is None: import requests
    return requests

def get_winreg():
    global winreg
    if winreg is None: import winreg
    return winreg

class RegionSelector:
    """Оверлей для выделения области."""
    def __init__(self, root, screenshot_img):
        self.root = tk.Toplevel(root)
        self.screenshot = screenshot_img
        self.result = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(cursor="cross")
        
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.bg_photo = ImageTk.PhotoImage(self.screenshot)
        
        self.canvas = tk.Canvas(self.root, width=sw, height=sh, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
        
        self.detail_rect = self.canvas.create_rectangle(0, 0, sw, sh, fill="black", stipple="gray50")

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def _on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id: self.canvas.delete(self.rect_id)

    def _on_drag(self, event):
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="#6c7bff", width=2)

    def _on_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        if (x2-x1) > 10 and (y2-y1) > 10:
            self.result = self.screenshot.crop((x1, y1, x2, y2))
        self.root.destroy()

class ScreenAIApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        
        # Load key or use fallback
        self.API_KEY = os.environ.get("OPENAI_API_KEY", "")
        
        if not self.API_KEY:
            self.API_KEY = self._ask_api_key()
            if not self.API_KEY:
                sys.exit(0)
                
        global OPENAI_API_KEY
        OPENAI_API_KEY = self.API_KEY
        
        self.current_model = "gpt-5.2"
        self.is_processing = False
        self.icon_cache = None
        
        self.ACCENT = "#6c7bff"
        self.BG_COLOR = "#121212"
        self.FG_COLOR = "#eeeeee"

        # Load history
        self.history = []
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except: pass

        self._create_tray()
        
        # Lazy load keyboard
        import keyboard
        keyboard.add_hotkey("alt+shift+a", lambda: self.root.after(0, self.capture_and_process))
        keyboard.add_hotkey("f10", lambda: self.root.after(0, self._region_select_thread))
        keyboard.add_hotkey("ctrl+shift+q", lambda: self.root.after(0, self.exit_app))

    def _ask_api_key(self):
        """Просим ключ у пользователя, если его нет в конфиге."""
        key = tk.simpledialog.askstring("Screen AI", "Введите OpenAI API Key:\n(он сохранится в .env)", parent=self.root)
        if key and key.strip():
            k = key.strip()
            with open(".env", "w", encoding="utf-8") as f:
                f.write(f"OPENAI_API_KEY={k}\n")
            return k
        return None

    def _create_icon(self):
        if self.icon_cache: return self.icon_cache
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(108, 123, 255))
        d.text((18, 12), "AI", fill="white", font_size=30)
        self.icon_cache = img
        return img

    def _notify(self, title, message):
        def _show():
            popup = tk.Toplevel(self.root)
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            popup.configure(bg=self.BG_COLOR)
            
            frame = tk.Frame(popup, bg=self.BG_COLOR, padx=20, pady=15, bd=0, highlightthickness=0)
            frame.pack()

            if title:
                tk.Label(frame, text=title.upper(), font=("Segoe UI", 9, "bold"), fg=self.ACCENT, bg=self.BG_COLOR).pack(anchor="w")
            
            tk.Label(frame, text=message[:600], font=("Segoe UI", 11), fg=self.FG_COLOR, bg=self.BG_COLOR, wraplength=400, justify="left").pack(anchor="w", pady=(5, 0))

            popup.update_idletasks()
            w, h = popup.winfo_reqwidth(), popup.winfo_reqheight()
            sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
            popup.geometry(f"{w}x{h}+20+{sh - h - 50}")
            
            popup.bind("<Button-1>", lambda e: popup.destroy())
            self.root.after(5000, lambda: popup.destroy())

        self.root.after(0, _show)

    def _save_history(self, txt, ans):
        self.history.append({"time": time.strftime("%H:%M"), "q": txt, "a": ans})
        if len(self.history) > 20: self.history.pop(0)
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except: pass

    def _show_history_window(self):
        if not self.history:
            self._notify("История", "Список пуст")
            return
            
        win = tk.Toplevel(self.root)
        win.title("История запросов")
        win.geometry("500x600")
        win.configure(bg=self.BG_COLOR)
        
        txt = tk.Text(win, bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Consolas", 10), padx=10, pady=10)
        txt.pack(fill="both", expand=True)
        
        for item in reversed(self.history):
            txt.insert("end", f"[{item['time']}] {item['q']}\n")
            txt.insert("end", f"➔ {item['a']}\n\n")
            
        txt.config(state="disabled")

    def _toggle_autostart(self):
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        name = "ScreenAI"
        path = sys.executable
        wr = get_winreg()
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, key, 0, wr.KEY_ALL_ACCESS) as reg:
                try:
                    wr.DeleteValue(reg, name)
                    self._notify("Автозапуск", "Отключено")
                except FileNotFoundError:
                    wr.SetValueEx(reg, name, 0, wr.REG_SZ, path)
                    self._notify("Автозапуск", "Включено")
        except Exception as e:
            self._notify("Ошибка", str(e))

    def _set_model(self, m):
        self.current_model = m
        self._notify("Модель", f"Выбрана: {MODELS[m]}")

    def _create_tray(self):
        import pystray
        
        def model_menu():
            return pystray.Menu(
                pystray.MenuItem("GPT-5.2 (Superior)", lambda: self._set_model("gpt-5.2"), checked=lambda i: self.current_model == "gpt-5.2"),
                pystray.MenuItem("GPT-4o (Smart)", lambda: self._set_model("gpt-4o"), checked=lambda i: self.current_model == "gpt-4o"),
                pystray.MenuItem("GPT-4o Mini (Fast)", lambda: self._set_model("gpt-4o-mini"), checked=lambda i: self.current_model == "gpt-4o-mini")
            )

        menu = pystray.Menu(
            pystray.MenuItem("📸 Скриншот (Alt+Shift+A)", lambda: self.root.after(0, self.capture_and_process)),
            pystray.MenuItem("🔍 Область (F10)", lambda: self.root.after(0, self._region_select_thread)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📝 История", lambda: self.root.after(0, self._show_history_window)),
            pystray.MenuItem("🧠 Выбор модели", model_menu()),
            pystray.MenuItem("🚀 Автозапуск", lambda: self.root.after(0, self._toggle_autostart)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🗑️ Удалить полностью", lambda: self.root.after(0, self.uninstall_app)),
            pystray.MenuItem("🚪 Выход", self.exit_app)
        )
        self.tray_icon = pystray.Icon("ScreenAI", self._create_icon(), "Screen AI", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _region_select_thread(self):
        if self.is_processing: return
        def task():
            sct = get_mss().mss()
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", (mon['width'], mon['height']), shot.rgb)
            self.root.after(0, lambda: self._run_selector(img))
        threading.Thread(target=task, daemon=True).start()

    def _run_selector(self, img):
        res = RegionSelector(self.root, img)
        def wait_res():
            if not self.root.winfo_exists(): return
            try:
                if res.root.winfo_exists(): self.root.after(100, wait_res)
                elif res.result: self.capture_and_process(res.result)
            except: pass
        wait_res()

    def capture_and_process(self, region_img=None):
        if self.is_processing:
            self._notify("Screen AI", "Подождите, запрос обрабатывается...")
            return
        
        self.is_processing = True
        
        def task():
            try:
                if region_img: img = region_img
                else:
                    sct = get_mss().mss()
                    mon = sct.monitors[1]
                    shot = sct.grab(mon)
                    img = Image.frombytes("RGB", (mon['width'], mon['height']), shot.rgb)
                
                buf = io.BytesIO()
                img.thumbnail(MAX_IMAGE_SIZE)
                img.save(buf, format="JPEG", quality=JPEG_QUALITY)
                b64 = base64.b64encode(buf.getvalue()).decode()
                
                payload = {
                    "model": self.current_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}
                    ]
                }
                
                if self.current_model == "gpt-5.2":
                    payload["max_completion_tokens"] = 150
                else:
                    payload["max_tokens"] = 150
                
                req = get_requests()
                r = req.post(OPENAI_API_URL, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, json=payload, timeout=30)
                
                if r.status_code != 200:
                    raise Exception(f"HTTP {r.status_code}: {r.text}")
                    
                ans = r.json()["choices"][0]["message"]["content"].strip()
                
                # Copy to clipboard
                self.root.clipboard_clear()
                self.root.clipboard_append(ans)
                self.root.update()
                
                self._save_history("Screenshot Analysis", ans)
                self._notify("AI (Скопировано)", ans)
                
            except Exception as e:
                err = str(e)
                if "Connection" in err: err = "Нет интернета"
                self._notify("Ошибка", err)
            finally:
                self.is_processing = False

        threading.Thread(target=task, daemon=True).start()

    def uninstall_app(self):
        if not messagebox.askyesno("Удаление", "Удалить программу ScreenAI и все данные?"):
            return

        # 1. Registry
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        name = "ScreenAI"
        wr = get_winreg()
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, key, 0, wr.KEY_ALL_ACCESS) as reg:
                wr.DeleteValue(reg, name)
        except: pass

        # 2. Files & Directories
        cmds = []
        
        # Shortcuts
        desktop = Path(os.path.expanduser("~/Desktop")) / "ScreenAI.lnk"
        startmenu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/ScreenAI.lnk"
        if desktop.exists(): cmds.append(f'del /f /q "{desktop}"')
        if startmenu.exists(): cmds.append(f'del /f /q "{startmenu}"')
        
        # AppData (Local and Roaming just in case)
        app_local = Path(os.environ["LOCALAPPDATA"]) / "ScreenAI"
        app_roaming = Path(os.environ["APPDATA"]) / "ScreenAI"
        if app_local.exists(): cmds.append(f'rmdir /s /q "{app_local}"')
        if app_roaming.exists(): cmds.append(f'rmdir /s /q "{app_roaming}"')

        # PyInstaller temporary extraction folder (_MEIPASS)
        if hasattr(sys, '_MEIPASS'):
            mei_dir = sys._MEIPASS
            cmds.append(f'rmdir /s /q "{mei_dir}"')

        # Self-destruct script
        exe_path = sys.executable
        pid = os.getpid()
        
        # Create a temp batch file to kill and delete
        bat_script = f"""
@echo off
:loop
tasklist | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 >nul
    goto loop
)
del "{exe_path}"
{' '.join(cmds)}
del "%~f0"
"""
        bat_file = Path(os.environ["TEMP"]) / "screenai_uninstall.bat"
        with open(bat_file, "w") as f:
            f.write(bat_script)
            
        os.startfile(bat_file)
        self.exit_app()

    def exit_app(self, *args):
        if hasattr(self, 'tray_icon'): self.tray_icon.stop()
        self.root.quit()
        os._exit(0)

    def run(self):
        self._notify("Screen AI v2.1", f"Готов! {MODELS[self.current_model]}\nAlt+Shift+A | F10")
        self.root.mainloop()

if __name__ == "__main__":
    ScreenAIApp().run()
