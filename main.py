#! /bin/python3

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import requests
import select
import os
import json
from evdev import InputDevice, ecodes, UInput

# XDG compliant per-user configuration path setup
CONFIG_DIR = os.path.expanduser("~/.config/penguin_handwriting")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "TOUCH_MAX_X": 1584,
    "TOUCH_MAX_Y": 924,
    "TOUCHPAD_PATH": "/dev/input/by-path/platform-b88000.i2c-event-mouse",
    "KEYBOARD_PATH": "/dev/input/by-path/platform-b88000.i2c-event-kbd",
    "WINDOW_WIDTH": 450,
    "WINDOW_HEIGHT": 300, # Increased slightly to accommodate dedicated error label cleanly
    "STROKE_COLOR": "#0078d7",
    "LANGUAGE": "Chinese (Simplified)"
}

LANGUAGE_MAP = {
    "Chinese (Simplified)": {"itc": "zh-t-i0-handwrit", "lang": "zh"},
    "Chinese (Traditional)": {"itc": "zh-hk-t-i0-handwrit", "lang": "zh"},
    "Japanese": {"itc": "ja-t-i0-handwrit", "lang": "ja"},
    "English": {"itc": "en-t-i0-handwrit", "lang": "en"}
}

class PenguinHandwriting:
    def __init__(self):
        self.load_config()
        self.enabled = True  

        self.root = tk.Tk()
        self.root.title("Penguin Handwriting")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        
        self.BG_COLOR = "#ffffff"
        self.CANDIDATE_BG = "#f3f3f3"
        self.TEXT_COLOR = "#000000"
        self.root.configure(bg=self.BG_COLOR)

        # Position Window
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{self.cfg['WINDOW_WIDTH']}x{self.cfg['WINDOW_HEIGHT']}+{screen_w - self.cfg['WINDOW_WIDTH'] - 20}+{screen_h - self.cfg['WINDOW_HEIGHT'] - 60}")

        # Top Bar
        self.top_bar = tk.Frame(self.root, bg=self.BG_COLOR, height=28)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)
        self.top_bar.pack_propagate(False)

        self.close_btn = tk.Button(
            self.top_bar, text="✕", font=("Arial", 9), 
            bg=self.BG_COLOR, fg="#777777", activebackground="#e81123", activeforeground="#ffffff",
            borderwidth=0, relief="flat", command=self.exit_application
        )
        self.close_btn.pack(side=tk.RIGHT, padx=5, fill=tk.Y)

        self.settings_btn = tk.Button(
            self.top_bar, text="⚙", font=("Arial", 11), 
            bg=self.BG_COLOR, fg="#555555", activebackground="#e1e1e1", activeforeground="#000000",
            borderwidth=0, relief="flat", command=self.open_config_window
        )
        self.settings_btn.pack(side=tk.RIGHT, padx=2, fill=tk.Y)

        self.status_label = tk.Label(self.top_bar, text="Penguin Handwriting Active (Ctrl + Alt + H to hide)", font=("Arial", 8, "bold"), fg="#22c55e", bg=self.BG_COLOR)
        self.status_label.pack(side=tk.LEFT, padx=10)

        # Canvas
        self.canvas = tk.Canvas(self.root, width=self.cfg['WINDOW_WIDTH'], height=self.cfg['WINDOW_HEIGHT'] - 130, 
                                bg=self.BG_COLOR, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-3>", lambda e: self.open_config_window()) 

        # Error UI Elements (Dedicated bottom container)
        self.error_frame = tk.Frame(self.root, bg="#fef2f2")
        self.error_label = tk.Label(self.error_frame, text="", font=("Arial", 9, "bold"), fg="#ef4444", bg="#fef2f2", anchor="w")
        self.error_frame.pack_forget()

        # Candidates Bar Master
        self.candidate_frame = tk.Frame(self.root, bg=self.CANDIDATE_BG)
        self.candidate_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # Tracking State Variables
        self.last_x, self.last_y = None, None
        self.is_touching = False
        self.current_candidates = []
        self.is_grabbed = False
        
        self.ink_data = [] 
        self.current_stroke_x = []
        self.current_stroke_y = []
        self.current_stroke_t = []
        
        self.max_x_in_current_stroke = 0
        self.prev_stroke_max_x = 0

        self.ocr_timer = None
        self.start_time = time.time()

        # Evdev Pipeline
        cap = {ecodes.EV_KEY: list(range(1, 255))}
        self.ui = UInput(cap, name="Penguin-Handwriting-Keyboard")
        self.kbd = None

        self.ctrl_pressed = False
        self.alt_pressed = False
        self.stop_threads = False

        threading.Thread(target=self.read_touchpad, daemon=True).start()
        threading.Thread(target=self.listen_global_keyboard, daemon=True).start()
        
        # Setup
        self.root.after(100, self.go_to_sleep_ui)
        self.root.after(100, self.sync_keyboard_grab_state)

    def load_config(self):
        if not os.path.exists(CONFIG_DIR):
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
            except Exception as e:
                print(f"Failed to create configuration directory: {e}")

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in self.cfg: self.cfg[k] = v
            except:
                self.cfg = DEFAULT_CONFIG.copy()
        else:
            self.cfg = DEFAULT_CONFIG.copy()
            self.save_config()

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.cfg, f, indent=4)
        except Exception as e:
            print(f"Failed to write configuration file: {e}")

    def toggle_ime(self):
        self.enabled = not self.enabled
        if self.enabled:
            self.root.deiconify()  # Reveal the window completely
            self.status_label.config(text="Penguin Handwriting Active (Ctrl + Alt + H to hide)", fg="#22c55e")
            self.go_to_sleep_ui()
        else:
            self.root.after(0, self.clear_canvas)
            self.root.withdraw()   # Completely hide the window layout 

    def wake_up_ui(self):
        if self.enabled:
            self.root.attributes("-alpha", 1.0)  

    def go_to_sleep_ui(self):
        if self.enabled:
            if not self.ink_data:
                self.root.attributes("-alpha", 0.4)
            else:
                self.root.attributes("-alpha", 0.9)
    
    def show_error(self, heading, message):
        self.error_label.config(text=f"{heading}: {message}")
        self.error_frame.pack(side=tk.BOTTOM, fill=tk.X, before=self.candidate_frame)

    def hide_error(self):
        self.error_label.config(text="")
        self.error_frame.pack_forget()

    def read_touchpad(self):
        try:
            device = InputDevice(self.cfg['TOUCHPAD_PATH'])
        except Exception as e:
            print(f"Touchpad Device Access Refused: {e}")
            return

        x, y = 0, 0
        for event in device.read_loop():
            if self.stop_threads: break
            if not self.enabled: continue
            
            if event.type == ecodes.EV_ABS:
                if event.code == ecodes.ABS_MT_POSITION_X:
                    x = int((event.value / self.cfg['TOUCH_MAX_X']) * self.cfg['WINDOW_WIDTH'])
                elif event.code == ecodes.ABS_MT_POSITION_Y:
                    y = int((event.value / self.cfg['TOUCH_MAX_Y']) * (self.cfg['WINDOW_HEIGHT'] - 95))
            
            elif event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH:
                self.is_touching = bool(event.value)
                if self.is_touching:
                    self.root.after(0, self.wake_up_ui)
                    self.root.after(0, self.hide_error)
                    if self.ocr_timer: self.root.after_cancel(self.ocr_timer)
                    
                    self.current_stroke_x, self.current_stroke_y, self.current_stroke_t = [], [], []
                    self.max_x_in_current_stroke = 0
                else:
                    if self.current_stroke_x:
                        self.ink_data.append([self.current_stroke_x, self.current_stroke_y, self.current_stroke_t])
                        self.prev_stroke_max_x = max(self.prev_stroke_max_x, self.max_x_in_current_stroke)

                    self.last_x, self.last_y = None, None
                    self.ocr_timer = self.root.after(400, self.perform_api_ocr)

            if event.type == ecodes.EV_SYN and self.is_touching:
                if x > self.max_x_in_current_stroke:
                    self.max_x_in_current_stroke = x
                self.root.after(0, self.draw_stroke, x, y)

    def sync_keyboard_grab_state(self):
        if self.stop_threads or not self.kbd or not self.enabled:
            if not self.stop_threads: self.root.after(100, self.sync_keyboard_grab_state)
            return
        try:
            if self.current_candidates and not self.is_grabbed:
                self.kbd.grab()
                self.is_grabbed = True
            elif not self.current_candidates and self.is_grabbed:
                self.kbd.ungrab()
                self.is_grabbed = False
        except:
            self.is_grabbed = False
        self.root.after(100, self.sync_keyboard_grab_state)

    def listen_global_keyboard(self):
        try:
            self.kbd = InputDevice(self.cfg['KEYBOARD_PATH'])
        except Exception as e:
            print(f"Keyboard Device Access Refused: {e}")
            return

        key_mapping = {
            ecodes.KEY_1: 0, ecodes.KEY_2: 1, ecodes.KEY_3: 2, ecodes.KEY_4: 3, ecodes.KEY_5: 4,
            ecodes.KEY_6: 5, ecodes.KEY_7: 6, ecodes.KEY_8: 7, ecodes.KEY_9: 8, ecodes.KEY_0: 9
        }

        while not self.stop_threads:
            try:
                r, w, x = select.select([self.kbd], [], [], 0.1)
                if r:
                    for event in self.kbd.read():
                        if event.type == ecodes.EV_KEY:
                            if event.code in [ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL]:
                                self.ctrl_pressed = bool(event.value)
                            if event.code in [ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT]:
                                self.alt_pressed = bool(event.value)

                            # Handle Toggle Hotkey (Ctrl + Alt + H)
                            if self.ctrl_pressed and self.alt_pressed and event.code == ecodes.KEY_H and event.value == 1:
                                self.root.after(0, self.toggle_ime)
                                continue

                            # Physical ESC key intercept to clear current inputs
                            if self.enabled and self.is_grabbed and event.code == ecodes.KEY_ESC and event.value == 1:
                                self.root.after(0, self.clear_canvas)
                                continue

                            if self.enabled and self.is_grabbed and event.code in key_mapping:
                                if event.value == 1:
                                    idx = key_mapping[event.code]
                                    if idx < len(self.current_candidates):
                                        char_string = self.current_candidates[idx]
                                        self.kbd.ungrab()
                                        self.is_grabbed = False
                                        self.root.after(0, self.select_string, char_string)
                                continue

                            if self.enabled and self.is_grabbed:
                                self.ui.write(ecodes.EV_KEY, event.code, event.value)
                                self.ui.syn()
            except:
                break

    def draw_stroke(self, x, y):
        if self.last_x is not None and self.last_y is not None:
            self.canvas.create_line(self.last_x, self.last_y, x, y, 
                                    fill=self.cfg['STROKE_COLOR'], width=4, capstyle=tk.ROUND)
        
        relative_ms = int((time.time() - self.start_time) * 1000)
        self.current_stroke_x.append(x)
        self.current_stroke_y.append(y)
        self.current_stroke_t.append(relative_ms)
        self.last_x, self.last_y = x, y

    def perform_api_ocr(self):
        if self.is_touching or not self.ink_data: return 
        threading.Thread(target=self.fetch_predictions, daemon=True).start()

    def fetch_predictions(self):
        lang_profile = LANGUAGE_MAP.get(self.cfg['LANGUAGE'], LANGUAGE_MAP["Chinese (Simplified)"])
        url = f"https://inputtools.google.com/request?itc={lang_profile['itc']}&num=10"
        payload = {
            "app": "coauthor", "device": "desktop", "input_type": "0",
            "requests": [{
                "writing_guide": {"width": self.cfg['WINDOW_WIDTH'], "height": self.cfg['WINDOW_HEIGHT'] - 130},
                "ink": self.ink_data, "language": lang_profile['lang']
            }]
        }
        try:
            response = requests.post(url, json=payload, timeout=3)
            if response.status_code == 200:
                result = response.json()
                if result[0] == "SUCCESS":
                    self.root.after(0, self.update_candidates, result[1][0][1])
            else:
                self.root.after(0, self.show_error, "Server Error", f"Status Code: {response.status_code}")

        except requests.exceptions.ConnectionError:
            self.root.after(0, self.show_error, "Offline Error", "Network unreachable.")

        except requests.exceptions.Timeout:
            self.root.after(0, self.show_error, "Timeout Error", "The connection timed out.")

        except requests.exceptions.RequestException as e:
            self.root.after(0, self.show_error, "API Error", "Connection failed.")

        except Exception as e:
            print(f"Handwriting Tool API Failure: {e}")
            self.root.after(0, self.show_error, "Unexpected Error", "Internal app exception.")

    def update_candidates(self, candidates):
        self.current_candidates = candidates[:10]
        for widget in self.candidate_frame.winfo_children(): widget.destroy()

        words_pane = tk.Frame(self.candidate_frame, bg=self.CANDIDATE_BG)
        words_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        actions_pane = tk.Frame(self.candidate_frame, bg=self.CANDIDATE_BG)
        actions_pane.pack(side=tk.RIGHT, fill=tk.Y)

        row1 = tk.Frame(words_pane, bg=self.CANDIDATE_BG)
        row1.pack(fill=tk.X, expand=True)
        row2 = tk.Frame(words_pane, bg=self.CANDIDATE_BG)
        row2.pack(fill=tk.X, expand=True)

        for i, char_string in enumerate(self.current_candidates):
            target_row = row1 if i < 5 else row2
            display_num = (i + 1) % 10  
            btn = tk.Button(target_row, text=f"{display_num}. {char_string}", font=("Arial", 10),
                            bg=self.BG_COLOR, fg=self.TEXT_COLOR, borderwidth=1, relief="groove",
                            command=lambda s=char_string: self.select_string(s))
            btn.pack(side=tk.LEFT, padx=1, pady=1, expand=True, fill=tk.BOTH)

        esc_btn = tk.Button(actions_pane, text="ESC", font=("Arial", 9, "bold"),
                            bg="#777777", fg="white", borderwidth=1, width=6, command=self.clear_canvas)
        esc_btn.pack(fill=tk.BOTH, expand=True, padx=2, pady=1)
        
        self.root.attributes("-alpha", 0.9)

    def select_string(self, char_string):
        for char in char_string:
            try:
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_U, 1)
                self.ui.syn(); time.sleep(0.008)
                
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_U, 0)
                self.ui.syn()
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
                self.ui.syn(); time.sleep(0.008)

                for hex_char in f"{ord(char):x}":
                    keycode = getattr(ecodes, f"KEY_{hex_char.upper()}")
                    self.ui.write(ecodes.EV_KEY, keycode, 1); self.ui.syn(); time.sleep(0.004)
                    self.ui.write(ecodes.EV_KEY, keycode, 0); self.ui.syn()

                self.ui.write(ecodes.EV_KEY, ecodes.KEY_ENTER, 1); self.ui.syn(); time.sleep(0.004)
                self.ui.write(ecodes.EV_KEY, ecodes.KEY_ENTER, 0); self.ui.syn()
            except Exception as e:
                print(f"Sequence Injection Error: {e}")
        self.clear_canvas()

    def clear_canvas(self):
        self.canvas.delete("all")
        self.hide_error()
        self.ink_data, self.current_candidates = [], []
        self.prev_stroke_max_x = 0
        try:
            if self.kbd and self.is_grabbed:
                self.kbd.ungrab()
                self.is_grabbed = False
        except: pass
        for widget in self.candidate_frame.winfo_children(): widget.destroy()
        self.go_to_sleep_ui()

    def open_config_window(self):
        if hasattr(self, 'config_win') and self.config_win.winfo_exists():
            self.config_win.lift()
            return

        self.config_win = tk.Toplevel(self.root)
        self.config_win.title("Penguin Handwriting - Settings")
        self.config_win.geometry("420x400")
        self.config_win.attributes("-topmost", True)
        self.config_win.resizable(False, False)

        main_frame = ttk.Frame(self.config_win, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Target Writing Language:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0,2))
        lang_var = tk.StringVar(value=self.cfg['LANGUAGE'])
        
        lang_combo = ttk.Combobox(main_frame, textvariable=lang_var, state="readonly", values=list(LANGUAGE_MAP.keys()))
        lang_combo.pack(fill=tk.X, pady=(0, 15))

        entries = {}
        fields = [
            ("TOUCHPAD_PATH", "Touchpad Input Node Event Path:"),
            ("KEYBOARD_PATH", "Keyboard Input Node Event Path:"),
            ("TOUCH_MAX_X", "Hardware Absolute Matrix Touch Max X:"),
            ("TOUCH_MAX_Y", "Hardware Absolute Matrix Touch Max Y:"),
            ("STROKE_COLOR", "Visual Ink Stroke Color Hex Code:")
        ]

        for key, label in fields:
            ttk.Label(main_frame, text=label, font=("Arial", 9)).pack(anchor=tk.W, pady=(2,0))
            entry = ttk.Entry(main_frame)
            entry.insert(0, str(self.cfg[key]))
            entry.pack(fill=tk.X, pady=(0, 10))
            entries[key] = entry

        def save_and_close():
            try:
                self.cfg['LANGUAGE'] = lang_var.get()
                self.cfg['TOUCHPAD_PATH'] = entries['TOUCHPAD_PATH'].get()
                self.cfg['KEYBOARD_PATH'] = entries['KEYBOARD_PATH'].get()
                self.cfg['TOUCH_MAX_X'] = int(entries['TOUCH_MAX_X'].get())
                self.cfg['TOUCH_MAX_Y'] = int(entries['TOUCH_MAX_Y'].get())
                self.cfg['STROKE_COLOR'] = entries['STROKE_COLOR'].get()
                
                self.save_config()
                messagebox.showinfo("Success", "Configuration saved!\nRestart to apply device path changes.", parent=self.config_win)
                self.config_win.destroy()
            except ValueError:
                messagebox.showerror("Error", "Validation failed. Layout bounds must be integers.", parent=self.config_win)

        ttk.Button(main_frame, text="Save Changes", command=save_and_close).pack(side=tk.RIGHT, pady=10)
        ttk.Button(main_frame, text="Cancel", command=self.config_win.destroy).pack(side=tk.RIGHT, padx=10, pady=10)

    def exit_application(self):
        self.stop_threads = True
        try:
            if self.kbd and self.is_grabbed: self.kbd.ungrab()
        except: pass
        self.ui.close()
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.exit_application()

if __name__ == "__main__":
    app = PenguinHandwriting()
    app.run()
