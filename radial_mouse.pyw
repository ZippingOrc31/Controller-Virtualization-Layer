import tkinter as tk
import threading
import pyautogui
import time
import ctypes
import sys
import subprocess
import os
import pystray
from PIL import Image, ImageDraw
from inputs import get_gamepad
from screeninfo import get_monitors

# Optional vJoy (safeguarded)
try:
    import pyvjoy
except Exception:
    pyvjoy = None

# Hide console window (Windows only)
if sys.platform == "win32":
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass


# -------- safe cursor move clamped to active monitor --------
def safe_move_in_monitor(x, y, mon):
    try:
        ix = max(mon.x + 1, min(mon.x + mon.width - 2, int(x)))
        iy = max(mon.y + 1, min(mon.y + mon.height - 2, int(y)))
        pyautogui.moveTo(ix, iy)
    except Exception as e:
        print("safe_move_in_monitor error:", e)


class MapperApp:
    def __init__(self, root):
        # ---- GUI base ----
        self.root = root
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.8)
        self.root.configure(bg="black")

        # Hide at start & create tray icon
        self.root.withdraw()
        self.create_tray_icon()

        # ---- State ----
        self.lock_gui = True
        self.joy_mouse = False
        self.holding_click = False
        self.holding_right = False
        self.rx_val, self.ry_val = 0, 0
        self.rx_neutral, self.ry_neutral = 652, -153
        self.deadzone = 0

        # ---- Multi-click detection ----
        self.r3_click_times = []
        self.l3_click_times = []
        self.multi_click_window = 0.6

        # ---- Monitors ----
        self.monitors = get_monitors()
        self.current_monitor_index = 0
        self.active_monitor = self.monitors[self.current_monitor_index]

        start_x, start_y = pyautogui.position()
        self.virtual_x, self.virtual_y = float(start_x), float(start_y)

        # ---- vJoy safeguard ----
        self.j = None
        if pyvjoy:
            try:
                self.j = pyvjoy.VJoyDevice(1)
                print("vJoy initialized")
            except Exception as e:
                print("vJoy unavailable:", e)
                self.j = None

        # ---- GUI ----
        self.rx_label = tk.Label(root, text="Right Stick X Axis: 0", fg="orange", bg="black")
        self.rx_label.pack(pady=5)

        self.ry_label = tk.Label(root, text="Right Stick Y Axis: 0", fg="lightgreen", bg="black")
        self.ry_label.pack(pady=5)

        self.status_label = tk.Label(root, text="Hold: OFF | Mouse: OFF", fg="red", bg="black")
        self.status_label.pack(pady=10)

        tk.Label(root, text="Acceleration (x100)", fg="white", bg="black").pack()
        self.accel_slider = tk.Scale(root, from_=5, to=50, orient=tk.HORIZONTAL, bg="black", fg="white")
        self.accel_slider.set(15)
        self.accel_slider.pack()

        tk.Label(root, text="Inertia (x100)", fg="white", bg="black").pack()
        self.inertia_slider = tk.Scale(root, from_=50, to=99, orient=tk.HORIZONTAL, bg="black", fg="white")
        self.inertia_slider.set(85)
        self.inertia_slider.pack()

        tk.Label(root, text="Trigger threshold", fg="white", bg="black").pack()
        self.threshold_slider = tk.Scale(root, from_=0, to=255, orient=tk.HORIZONTAL, bg="black", fg="white")
        self.threshold_slider.set(200)
        self.threshold_slider.pack()

        self.btn_mouse = tk.Button(root, text="🖱️ Joystick → Mouse: OFF", command=self.toggle_joy_mouse)
        self.btn_mouse.pack(pady=5)

        self.btn_lock = tk.Button(root, text="🔒 GUI Lock: ON", command=self.toggle_gui_lock)
        self.btn_lock.pack(pady=5)

        self.btn_keyboard = tk.Button(root, text="⌨️ On-Screen Keyboard", command=self.open_onscreen_keyboard)
        self.btn_keyboard.pack(pady=5)

        self.btn_exit = tk.Button(root, text="❌ Exit", command=self.exit_program)
        self.btn_exit.pack(pady=5)

        tk.Label(root,
            text="LT=left hold | RT=right hold | R3 x4=mouse toggle | L3=swap monitor",
            fg="white", bg="black"
        ).pack(pady=5)

        # Threads
        threading.Thread(target=self.listen_controller, daemon=True).start()
        threading.Thread(target=self.update_mouse_loop, daemon=True).start()
        threading.Thread(target=self.watchdog_loop, daemon=True).start()


    # =========================================
    # ✅ TRAY ICON FUNCTIONS
    # =========================================
    def create_tray_icon(self):
        def icon_img():
            img = Image.new("RGB", (64,64), "black")
            draw = ImageDraw.Draw(img)
            draw.rectangle((5,5,59,59), outline="white")
            draw.text((17,23), "GP", fill="white")
            return img

        menu = pystray.Menu(
            pystray.MenuItem("Show Window", self.show_window),
            pystray.MenuItem("Hide Window", self.hide_window),
            pystray.MenuItem("Toggle Mouse Mode", self.toggle_joy_mouse),
            pystray.MenuItem("Exit", self.exit_program)
        )

        self.tray_icon = pystray.Icon("gpmapper", icon_img(), "Gamepad Mapper", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.overrideredirect(True)

    def exit_program(self, *args):
        try: self.tray_icon.stop()
        except: pass
        os._exit(0)


    # =========================================
    # ✅ UI / TOGGLE FUNCTIONS
    # =========================================
    def update_status(self):
        hold = "ON" if self.holding_click else "OFF"
        mouse = "ON" if self.joy_mouse else "OFF"
        self.status_label.config(
            text=f"Hold: {hold} | Mouse: {mouse}",
            fg="green" if self.holding_click or self.joy_mouse else "red",
        )

    def toggle_joy_mouse(self, *a):
        self.joy_mouse = not self.joy_mouse
        self.btn_mouse.config(text=f"🖱️ Joystick → Mouse: {'ON' if self.joy_mouse else 'OFF'}")
        if self.joy_mouse:
            mx, my = pyautogui.position()
            self.virtual_x, self.virtual_y = float(mx), float(my)
        self.update_status()

    def toggle_gui_lock(self):
        self.lock_gui = not self.lock_gui
        if self.lock_gui:
            self.root.overrideredirect(True)
            self.btn_lock.config(text="🔒 GUI Lock: ON")
        else:
            self.root.overrideredirect(False)
            self.btn_lock.config(text="🔓 GUI Lock: OFF")

    def open_onscreen_keyboard(self):
        try:
            shortcut = os.path.expandvars(
                r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Accessibility\On-Screen Keyboard.lnk"
            )
            subprocess.Popen(['cmd', '/c', 'start', '', shortcut], shell=True)
        except Exception as e:
            print("Failed to open OSK:", e)


    # =========================================
    # ✅ CONTROLLER LOOP
    # =========================================
    def listen_controller(self):
        while True:
            try:
                for event in get_gamepad():

                    if event.code == "ABS_RX":
                        self.rx_val = event.state
                        self.rx_label.config(text=f"Right Stick X Axis: {self.rx_val}")

                    elif event.code == "ABS_RY":
                        self.ry_val = event.state
                        self.ry_label.config(text=f"Right Stick Y Axis: {self.ry_val}")

                    elif event.code == "ABS_Z":
                        threshold = int(self.threshold_slider.get())
                        if event.state > threshold and not self.holding_click:
                            pyautogui.mouseDown(x=int(self.virtual_x), y=int(self.virtual_y))
                            self.holding_click = True
                            self.update_status()
                        elif event.state <= threshold and self.holding_click:
                            pyautogui.mouseUp(x=int(self.virtual_x), y=int(self.virtual_y))
                            self.holding_click = False
                            self.update_status()

                    elif event.code == "ABS_RZ":
                        threshold = int(self.threshold_slider.get())
                        if event.state > threshold and not self.holding_right:
                            pyautogui.mouseDown(button="right",
                                                x=int(self.virtual_x), y=int(self.virtual_y))
                            self.holding_right = True
                        elif event.state <= threshold and self.holding_right:
                            pyautogui.mouseUp(button="right",
                                              x=int(self.virtual_x), y=int(self.virtual_y))
                            self.holding_right = False

                    elif event.code == "BTN_THUMBR" and event.state == 1:
                        now = time.time()
                        self.r3_click_times = [t for t in self.r3_click_times if now - t < self.multi_click_window]
                        self.r3_click_times.append(now)

                        if len(self.r3_click_times) >= 4:
                            self.toggle_joy_mouse()
                            self.r3_click_times.clear()

                    elif event.code == "BTN_THUMBL" and event.state == 1:
                        self.swap_monitor()

                time.sleep(0)
            except Exception as e:
                print("Controller loop error:", e)
                time.sleep(0.1)


    # =========================================
    # ✅ MOUSE MOVEMENT
    # =========================================
    def swap_monitor(self):
        self.current_monitor_index = (self.current_monitor_index + 1) % len(self.monitors)
        self.active_monitor = self.monitors[self.current_monitor_index]
        cx = self.active_monitor.x + self.active_monitor.width // 2
        cy = self.active_monitor.y + self.active_monitor.height // 2
        self.virtual_x, self.virtual_y = float(cx), float(cy)
        safe_move_in_monitor(self.virtual_x, self.virtual_y, self.active_monitor)

    def update_mouse_loop(self):
        mx, my = pyautogui.position()
        virtual_x, virtual_y = float(mx), float(my)
        self.virtual_x, self.virtual_y = virtual_x, virtual_y

        while True:
            try:
                if self.joy_mouse:
                    mon = self.active_monitor

                    rx_offset = self.rx_val - self.rx_neutral
                    ry_offset = self.ry_val - self.ry_neutral

                    dx = rx_offset / 16384.0
                    dy = ry_offset / 16384.0

                    target_x = mon.x + mon.width//2 + dx*(mon.width//2)
                    target_y = mon.y + mon.height//2 - dy*(mon.height//2)

                    accel = float(self.accel_slider.get()) / 100.0
                    inertia = float(self.inertia_slider.get()) / 100.0

                    virtual_x = virtual_x * inertia + target_x * accel
                    virtual_y = virtual_y * inertia + target_y * accel

                    virtual_x = max(mon.x, min(mon.x + mon.width - 1, virtual_x))
                    virtual_y = max(mon.y, min(mon.y + mon.height - 1, virtual_y))

                    self.virtual_x, self.virtual_y = virtual_x, virtual_y
                    safe_move_in_monitor(self.virtual_x, self.virtual_y, mon)

                time.sleep(0)
            except Exception as e:
                print("Mouse loop error:", e)
                time.sleep(0.02)


    # =========================================
    # ✅ WATCHDOG
    # =========================================
    def reset_mouse_mode(self):
        print("Watchdog: resetting mouse mode…")
        if self.joy_mouse:
            self.joy_mouse = False
            self.update_status()
        time.sleep(0.1)
        self.toggle_joy_mouse()

    def watchdog_loop(self):
        last_x, last_y = pyautogui.position()
        last_time = time.time()
        while True:
            time.sleep(0.5)
            try:
                if self.joy_mouse:
                    cx, cy = pyautogui.position()
                    active = (
                        abs(self.rx_val - self.rx_neutral) > self.deadzone or
                        abs(self.ry_val - self.ry_neutral) > self.deadzone
                    )
                    if active:
                        if (cx, cy) == (last_x, last_y) and (time.time() - last_time) > 1.0:
                            self.reset_mouse_mode()
                            last_time = time.time()
                        else:
                            last_time = time.time()
                    last_x, last_y = cx, cy
            except Exception as e:
                print("Watchdog error:", e)


# ---- ENTRY ----
if __name__ == "__main__":
    root = tk.Tk()
    app = MapperApp(root)
    root.mainloop()
