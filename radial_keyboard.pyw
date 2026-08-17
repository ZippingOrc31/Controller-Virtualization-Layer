import tkinter as tk
import threading
import time
import keyboard
from inputs import get_gamepad
import pystray
from PIL import Image, ImageDraw

class RadialKeyboardApp:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        self.root.configure(bg="black")
        self.combo_active = False  # For press-to-toggle

        # Modes
        self.modes = ["alphabet", "caps", "symbols", "numbers", "combos"]
        self.mode_index = 0

        # Radial characters
        self.radial_modes = {
            "alphabet": {
                "center": ["esc","backspace","enter","space"], 
                "up": ["a","b","c","d"],
                "down": ["e","f","g","h"],
                "left": ["i","j","k","l"],
                "right": ["m","n","o","p"],
                "diag_ul": ["q","r","s","t"],
                "diag_ur": ["u","v","w","x"],
                "diag_dl": ["y","z",".",","],
                "diag_dr": ["!","?","'","\""]
            },
            "caps": {
                "center": ["esc","backspace","enter","space"],
                "up": ["A","B","C","D"],
                "down": ["E","F","G","H"],
                "left": ["I","J","K","L"],
                "right": ["M","N","O","P"],
                "diag_ul": ["Q","R","S","T"],
                "diag_ur": ["U","V","W","X"],
                "diag_dl": ["Y","Z",".",","],
                "diag_dr": ["!","?","'","\""]
            },
            "symbols": {
                "center": ["esc","backspace","enter","space"],
                "up": ["!","@","#","$"],
                "down": ["%","^","&","*"],
                "left": ["(",")","[","]"],
                "right": ["{","}","<",">"],
                "diag_ul": ["+","-","=","/"],
                "diag_ur": ["\\","|","_","~"],
                "diag_dl": [":",";","`","'"],
                "diag_dr": [".",",","?","!"]
            },
            "numbers": {
                "center": ["esc","backspace","enter","space"],
                "up": ["1","2","3","4"],
                "down": ["5","6","7","8"],
                "left": ["9","0","+","-"],
                "right": ["=","/","*","%"],
                "diag_ul": ["(",")","[","]"],
                "diag_ur": ["{","}","<",">"],
                "diag_dl": [".",",",";",":"],
                "diag_dr": ["^","&","|","~"]
            },
            "combos": {
                "center": ["esc","backspace","enter","space"],
                "up": ["ctrl+c","ctrl+v","ctrl+x","ctrl+z"],
                "down": ["alt+tab","alt+f4","win+d","win+tab"],
                "left": ["shift","ctrl","alt","win"],
                "right": ["home","end","pgup","pgdn"],
                "diag_ul": ["left","right","up","down"],
                "diag_ur": ["tab","esc","enter","space"],
                "diag_dl": ["copy","paste","cut","undo"],
                "diag_dr": ["ctrl+s","ctrl+f","ctrl+n","ctrl+t"]
            }
        }

        self.layout = [
            ["diag_ul","up","diag_ur"],
            ["left","center","right"],
            ["diag_dl","down","diag_dr"]
        ]

        self.small_center_font = ("TkDefaultFont", 9)
        self.small_center_font_active = ("TkDefaultFont", 10, "bold")
        self.char_font = ("TkDefaultFont", 10)
        self.char_font_active = ("TkDefaultFont", 12, "bold")

        self.cell_size = (120,80)
        self.cells = []
        self.sel_row, self.sel_col = 1,1

        for r,row in enumerate(self.layout):
            cell_row=[]
            for c,key in enumerate(row):
                frame = tk.Frame(self.root,bg="black",relief="ridge",bd=2,width=self.cell_size[0],height=self.cell_size[1])
                frame.grid(row=r,column=c,padx=2,pady=2)
                frame.grid_propagate(False)

                lbl_top=tk.Label(frame,bg="black",fg="white")
                lbl_left=tk.Label(frame,bg="black",fg="white")
                lbl_right=tk.Label(frame,bg="black",fg="white")
                lbl_bottom=tk.Label(frame,bg="black",fg="white")

                lbl_top.place(relx=0.5,rely=0.0,anchor="n")
                lbl_left.place(relx=0.0,rely=0.5,anchor="w")
                lbl_right.place(relx=1.0,rely=0.5,anchor="e")
                lbl_bottom.place(relx=0.5,rely=1.0,anchor="s")

                cell_row.append({
                    "frame":frame,
                    "labels":{"Y":lbl_top,"X":lbl_left,"B":lbl_right,"A":lbl_bottom},
                    "key":key
                })
            self.cells.append(cell_row)

        self.status=tk.Label(self.root,text="Radial Overlay: Inactive",fg="red",bg="black")
        self.status.grid(row=3,column=0,columnspan=3)

        self.active=False
        self.moving_window=False
        self.hat_x=0
        self.hat_y=0

        # L3 double press timing
        self.last_l3_press = 0

        self.update_labels()
        self.apply_cell_styles()

        # Start controller thread
        threading.Thread(target=self.controller_loop,daemon=True).start()

        # Create tray icon
        self.create_tray_icon()

    def current_radials(self): return self.radial_modes[self.modes[self.mode_index]]
    def get_chars_for_key(self,key): return self.current_radials().get(key,["","","",""])

    def move_window(self, dx, dy):
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def update_labels(self):
        def _u():
            for r,row in enumerate(self.cells):
                for c,cell in enumerate(row):
                    key=cell["key"]
                    chars=self.get_chars_for_key(key)
                    lbls=cell["labels"]
                    font = self.small_center_font if key=="center" else self.char_font
                    lbls["Y"].config(text=chars[3], font=font)
                    lbls["X"].config(text=chars[2], font=font)
                    lbls["B"].config(text=chars[1], font=font)
                    lbls["A"].config(text=chars[0], font=font)
        self.root.after(0,_u)

    def apply_cell_styles(self):
        def _s():
            for r,row in enumerate(self.cells):
                for c,cell in enumerate(row):
                    frame=cell["frame"]
                    selected=(r==self.sel_row and c==self.sel_col)
                    frame.config(bd=(4 if selected else 2))
                    for lbl in cell["labels"].values():
                        if cell["key"]=="center":
                            lbl.config(font=self.small_center_font_active if selected else self.small_center_font)
                        else:
                            lbl.config(font=self.char_font_active if selected else self.char_font)
        self.root.after(0,_s)

    def set_selected(self,r,c):
        self.sel_row,self.sel_col = r,c
        self.apply_cell_styles()

    def update_selection(self):
        if self.hat_x==-1 and self.hat_y==-1: self.set_selected(0,0)
        elif self.hat_x==1 and self.hat_y==-1: self.set_selected(0,2)
        elif self.hat_x==-1 and self.hat_y==1: self.set_selected(2,0)
        elif self.hat_x==1 and self.hat_y==1: self.set_selected(2,2)
        elif self.hat_x==-1: self.set_selected(1,0)
        elif self.hat_x==1: self.set_selected(1,2)
        elif self.hat_y==-1: self.set_selected(0,1)
        elif self.hat_y==1: self.set_selected(2,1)
        else: self.set_selected(1,1)

    def type_key(self,key):
        if "+" in key:
            parts = key.split("+")
            for p in parts[:-1]: keyboard.press(p)
            keyboard.send(parts[-1])
            for p in parts[:-1]: keyboard.release(p)
        else:
            keyboard.send(key)
        self.root.after(0,lambda:self.status.config(text=f"{self.modes[self.mode_index]}: {key}", fg="green"))

    def press_char_visual(self,face,pressed=True):
        lbl=self.cells[self.sel_row][self.sel_col]["labels"].get(face)
        if lbl:
            size = 12 if pressed else 10
            lbl.config(font=("TkDefaultFont",size))

    def handle_button(self,button_index,pressed=True):
        map_face={0:"A",1:"B",2:"X",3:"Y"}
        face=map_face.get(button_index)
        self.press_char_visual(face,pressed)
        if pressed:
            key_label=self.layout[self.sel_row][self.sel_col]
            chars=self.get_chars_for_key(key_label)
            key=chars[button_index]
            if key: self.type_key(key)

    def create_tray_icon(self):
        # Simple cyan square icon
        img = Image.new('RGB', (64, 64), color='black')
        d = ImageDraw.Draw(img)
        d.rectangle([16,16,48,48], fill='cyan')

        def on_quit(icon, item):
            self.root.destroy()
            icon.stop()

        menu = pystray.Menu(pystray.MenuItem('Exit', on_quit))
        self.tray_icon = pystray.Icon("RadialKeyboard", img, "Radial Keyboard", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def controller_loop(self):
        l3=r3=rb=lb=0
        hat_x=hat_y=0

        while True:
            try:
                for event in get_gamepad():
                    # Button map
                    if event.code=="BTN_THUMBL":
                        if event.state == 1:
                            now = time.time()
                            if now - self.last_l3_press < 0.3:
                                self.moving_window = not self.moving_window
                                self.status.config(
                                    text="Drag Window Mode" if self.moving_window else "Typing Mode",
                                    fg="yellow" if self.moving_window else "cyan"
                                )
                            self.last_l3_press = now
                        l3 = event.state

                    elif event.code=="BTN_THUMBR": r3=event.state
                    elif event.code=="BTN_TR": rb = event.state
                    elif event.code=="BTN_TL": lb = event.state

                    # DPAD select
                    if event.code=="ABS_HAT0X":
                        hat_x = event.state; self.hat_x = hat_x; self.update_selection()
                    elif event.code=="ABS_HAT0Y":
                        hat_y = event.state; self.hat_y = hat_y; self.update_selection()

                    # Press-to-toggle overlay
                    if l3==1 and r3==1 and rb==1 and lb==1:
                        if not self.combo_active:
                            self.active = not self.active
                            if self.active:
                                self.root.after(0,self.root.deiconify)
                                self.status.config(text="Radial: Active", fg="green")
                            else:
                                self.root.after(0,self.root.withdraw)
                                self.status.config(text="Radial: Inactive", fg="red")
                            self.combo_active = True
                    else:
                        self.combo_active = False

                    # Window drag mode
                    if self.moving_window:
                        if event.code=="ABS_RX":
                            x = event.state / 32768
                            if abs(x) > 0.15: self.move_window(x*8,0)
                        elif event.code=="ABS_RY":
                            y = event.state / 32768
                            if abs(y) > 0.15: self.move_window(0,y*8)
                        continue

                    # Typing mode
                    if self.active:
                        if event.code=="BTN_SOUTH": self.handle_button(0,event.state==1)
                        elif event.code=="BTN_EAST": self.handle_button(1,event.state==1)
                        elif event.code=="BTN_WEST": self.handle_button(2,event.state==1)
                        elif event.code=="BTN_NORTH": self.handle_button(3,event.state==1)

                        # Mode switch LB / RB
                        if event.code=="BTN_TR" and event.state==1:
                            self.mode_index=(self.mode_index+1)%len(self.modes)
                            self.update_labels()
                        if event.code=="BTN_TL" and event.state==1:
                            self.mode_index=(self.mode_index-1)%len(self.modes)
                            self.update_labels()
            except Exception as e:
                print("Controller loop error:", e)

if __name__=="__main__":
    root=tk.Tk()
    app=RadialKeyboardApp(root)
    root.withdraw()  # Start hidden
    root.mainloop()



