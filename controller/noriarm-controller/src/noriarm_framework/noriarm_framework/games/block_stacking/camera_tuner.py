import cv2
import subprocess
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import threading
import json
import os
import sys
import time
import re

# 카메라 고유 ID 정의 (기기 고유 ID 기반 - 포트 변경 무관)
CAMERA_IDS = {
    "front": "usb-Alcorlink_Corp._USB_2.0_Camera-video-index0"
}

def get_actual_index(target):
    """카메라 이름(front, wrist, side) 또는 인덱스 번호를 기반으로 현재 /dev/videoX 번호 반환"""
    if str(target).isdigit():
        return int(target)

    alias = target.lower()
    # top은 front와 동일하게 취급
    if alias == "top": alias = "front"

    if alias in CAMERA_IDS:
        id_path = CAMERA_IDS[alias]
        # 1. by-path 검색
        # 2. by-id 검색
        for base in ["/dev/v4l/by-path", "/dev/v4l/by-id"]:
            full_path = os.path.join(base, id_path)
            if os.path.exists(full_path):
                real_path = os.path.realpath(full_path)
                return int("".join(filter(str.isdigit, os.path.basename(real_path))))

    # 기본값 (검색 실패 시)
    defaults = {"front": 0}
    return defaults.get(alias, 0)

def get_settings_path(target):
    """카메라 이름에 따른 설정 파일 경로 반환"""
    if str(target).isdigit():
        # 인덱스로 들어온 경우 역으로 이름을 찾음
        idx = int(target)
        for name in CAMERA_IDS:
            if get_actual_index(name) == idx:
                return f"camera_settings_{name}.json"
        return f"camera_settings_v{idx}.json"

    alias = target.lower()
    if alias == "top": alias = "front"
    return f"camera_settings_{alias}.json"

# 인자값 처리
CAP_ALIAS = "front"
CAP_INDEX = 0
APPLY_ONLY = False

if __name__ == "__main__":
    for arg in sys.argv[1:]:
        if arg == "--apply":
            APPLY_ONLY = True
        else:
            CAP_ALIAS = arg
            CAP_INDEX = get_actual_index(arg)

    DEVICE = f"/dev/video{CAP_INDEX}"
    # 이제 이름 기반으로 설정 파일을 찾습니다.
    SETTINGS_FILE = get_settings_path(CAP_ALIAS)

    def ensure_permissions():
        """비밀번호 입력을 위해 미리 sudo 세션을 열고 권한 부여"""
        try:
            if os.access(DEVICE, os.W_OK): return True
            print(f"🔐 Unlocking {DEVICE}...")
            subprocess.run(f"sudo chmod 666 {DEVICE}", shell=True)
            return True
        except:
            return False

    def get_hw_controls():
        controls = {}
        try:
            result = subprocess.check_output(f"v4l2-ctl -d {DEVICE} --list-ctrls", shell=True).decode()
            for line in result.split('\n'):
                if not line.strip() or ':' not in line: continue
                name_part, spec_part = line.split(':', 1)
                name = name_part.strip().split(' ', 1)[0]
                m_min = re.search(r'min=(-?\d+)', spec_part)
                m_max = re.search(r'max=(-?\d+)', spec_part)
                m_def = re.search(r'default=(-?\d+)', spec_part)
                m_val = re.search(r'value=(-?\d+)', spec_part)
                if m_min and m_max:
                    controls[name] = {
                        "min": int(m_min.group(1)),
                        "max": int(m_max.group(1)),
                        "def": int(m_def.group(1)) if m_def else 0,
                        "val": int(m_val.group(1)) if m_val else 0,
                        "inactive": 'inactive' in spec_part
                    }
        except: pass
        return controls

    def set_v4l2(control, value, use_sudo=False):
        # 카메라 device 가 crw-rw-rw- 면 sudo 불필요. 사용자가 video group 멤버이거나
        # udev rule 로 권한 666 인 환경에서 default=False — control-service (데몬) 가
        # subprocess 로 호출 시 sudo 비밀번호 입력 불가하므로 hang 방지.
        prefix = "sudo " if use_sudo else ""
        cmd = f"{prefix}v4l2-ctl -d {DEVICE} -c {control}={value}"
        subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    def apply_saved_settings():
        ensure_permissions()
        if not os.path.exists(SETTINGS_FILE):
            print(f"⚠️  No settings file found for {CAP_ALIAS} ({SETTINGS_FILE})")
            return False

        hw_info = get_hw_controls()
        try:
            with open(SETTINGS_FILE, "r") as f: s = json.load(f)
            checks = s.get("checks", {})
            for k, v in checks.items():
                if k in hw_info:
                    on_val, off_val = (3, 1) if k == "auto_exposure" else (1, 0)
                    set_v4l2(k, on_val if v else off_val)
                    time.sleep(0.1)

            for k, v in s.get("sliders", {}).items():
                if k in hw_info:
                    if k == "exposure_time_absolute" and checks.get("auto_exposure", True): continue
                    if k == "white_balance_temperature" and checks.get("white_balance_automatic", True): continue
                    if k == "focus_absolute" and checks.get("focus_automatic_continuous", True): continue
                    set_v4l2(k, v)
                    time.sleep(0.05)
            print(f"✅ Applied settings from {SETTINGS_FILE} to {DEVICE}")
            return True
        except Exception as e:
            print(f"❌ Failed to apply settings: {e}")
            return False
    class CameraTunerApp:
        def __init__(self, root):
            print(f"🚀 Starting Tuner for {CAP_ALIAS} at {DEVICE}...")
            ensure_permissions()
            apply_saved_settings()

            self.hw_info = get_hw_controls()
            self.root = root
            self.root.title(f"Camera Master Tuner - {CAP_ALIAS} ({DEVICE})")
            self.root.geometry("1200x850")
            self.root.configure(bg="#000000")

            self.style = ttk.Style(); self.style.theme_use('clam')
            self.style.configure("TFrame", background="#000000")
            self.style.configure("TLabel", background="#000000", foreground="#FFFFFF", font=("Arial", 9, "bold"))
            self.style.configure("Group.TLabelframe", background="#000000", foreground="#00FFCC")
            self.style.configure("Group.TLabelframe.Label", background="#000000", foreground="#00FFCC", font=("Arial", 10, "bold"))

            self.main_container = ttk.Frame(self.root); self.main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
            self.canvas = tk.Canvas(self.main_container, width=640, height=480, bg="#111111", highlightthickness=1, highlightbackground="#00FFCC"); self.canvas.pack(anchor=tk.CENTER, pady=5)

            self.ctrl_container = ttk.Frame(self.main_container); self.ctrl_container.pack(side=tk.TOP, fill=tk.X, pady=10)
            self.col1 = ttk.Frame(self.ctrl_container); self.col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            self.col2 = ttk.Frame(self.ctrl_container); self.col2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            self.col3 = ttk.Frame(self.ctrl_container); self.col3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

            self.btn_frame = ttk.Frame(self.root); self.btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)
            tk.Button(self.btn_frame, text="🔄 RESET ALL", command=self.reset_to_default, bg="#444444", fg="#FFFFFF", font=("Arial", 10, "bold"), width=12, pady=8).pack(side=tk.LEFT, padx=5)
            self.save_btn = tk.Button(self.btn_frame, text=f"💾 SAVE SETTINGS FOR {CAP_ALIAS}", command=self.save_settings, bg="#00FFCC", fg="#000000", font=("Arial", 12, "bold"), pady=10); self.save_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

            self.sliders = {}; self.vars = {}
            self.build_ui()

            self.cap = cv2.VideoCapture(CAP_INDEX)
            self.update_video()

        def build_ui(self):
            g1 = ttk.LabelFrame(self.col1, text=" Basic Color ", style="Group.TLabelframe"); g1.pack(fill=tk.X, pady=5)
            for k in ["brightness", "contrast", "saturation", "hue"]: self.add_dynamic_slider(g1, k)
            g2 = ttk.LabelFrame(self.col2, text=" Quality & Light ", style="Group.TLabelframe"); g2.pack(fill=tk.X, pady=5)
            for k in ["gamma", "gain", "sharpness", "backlight_compensation"]: self.add_dynamic_slider(g2, k)
            g3 = ttk.LabelFrame(self.col3, text=" Camera & Focus ", style="Group.TLabelframe"); g3.pack(fill=tk.X, pady=5)
            row = ttk.Frame(g3); row.pack(fill=tk.X, pady=2)
            if "auto_exposure" in self.hw_info: self.add_check(row, "Auto Expo", "auto_exposure", 3, 1)
            if "white_balance_automatic" in self.hw_info: self.add_check(row, "Auto WB", "white_balance_automatic", 1, 0)
            if "focus_automatic_continuous" in self.hw_info: self.add_check(row, "Auto Focus", "focus_automatic_continuous", 1, 0)
            for k in ["exposure_time_absolute", "white_balance_temperature", "focus_absolute", "zoom_absolute"]: self.add_dynamic_slider(g3, k)

        def add_dynamic_slider(self, parent, key):
            if key not in self.hw_info: return
            spec = self.hw_info[key]; name = key.replace("_", " ").title()
            frame = ttk.Frame(parent); frame.pack(fill=tk.X, padx=10, pady=2)
            lbl = tk.Label(frame, text=f"{name}: {spec['val']}", font=("Arial", 8, "bold"), bg="#000000", fg="#FFFFFF", width=16, anchor="w"); lbl.pack(side=tk.LEFT)
            slider = tk.Scale(frame, from_=spec['min'], to=spec['max'], orient=tk.HORIZONTAL, bg="#000000", fg="#00FFCC", highlightthickness=0, troughcolor="#222222", showvalue=0, width=10, command=lambda v, l=lbl, n=name, c=key: self.on_slider_move(v, l, n, c))
            slider.set(spec['val']); slider.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0)); self.sliders[key] = (slider, lbl, name)

        def add_check(self, parent, label_text, cmd_name, on_val, off_val):
            curr_val = self.hw_info[cmd_name]["val"]
            var = tk.IntVar(value=1 if curr_val == on_val else 0)
            self.vars[cmd_name] = (var, on_val, off_val)
            tk.Checkbutton(parent, text=label_text, variable=var, bg="#000000", fg="#00FFCC", selectcolor="#000000", activebackground="#000000", activeforeground="#00FFCC", font=("Arial", 8, "bold"), command=lambda: self.async_set_v4l2(cmd_name, on_val if var.get() else off_val)).pack(side=tk.LEFT, padx=2)

        def on_slider_move(self, val, label, name, cmd):
            val = int(float(val)); label.config(text=f"{name}: {val}")
            if cmd == "exposure_time_absolute" and self.vars.get("auto_exposure", [None])[0] and self.vars["auto_exposure"][0].get(): return
            if cmd == "white_balance_temperature" and self.vars.get("white_balance_automatic", [None])[0] and self.vars["white_balance_automatic"][0].get(): return
            if cmd == "focus_absolute" and self.vars.get("focus_automatic_continuous", [None])[0] and self.vars["focus_automatic_continuous"][0].get(): return
            self.async_set_v4l2(cmd, val)

        def async_set_v4l2(self, control, value):
            threading.Thread(target=set_v4l2, args=(control, value), daemon=True).start()

        def reset_to_default(self):
            for k, spec in self.hw_info.items():
                if k in self.sliders: self.sliders[k][0].set(spec['def']); self.sliders[k][1].config(text=f"{self.sliders[k][2]}: {spec['def']}")
                self.async_set_v4l2(k, spec['def'])

        def save_settings(self):
            data = {"sliders": {k: int(v[0].get()) for k, v in self.sliders.items()}, "checks": {k: v[0].get() for k, v in self.vars.items()}}
            with open(SETTINGS_FILE, "w") as f: json.dump(data, f, indent=4)
            self.save_btn.config(text=f"✅ SAVED!", bg="#FFFFFF"); self.root.after(1000, lambda: self.save_btn.config(text=f"💾 SAVE SETTINGS FOR {CAP_ALIAS}", bg="#00FFCC"))

        def update_video(self):
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.resize(frame, (640, 480))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Correct: OpenCV BGR -> PIL RGB
                img = ImageTk.PhotoImage(image=Image.fromarray(frame))
                self.canvas.create_image(320, 240, anchor=tk.CENTER, image=img)
                self.canvas.img = img
            self.root.after(30, self.update_video)

    if APPLY_ONLY:
        apply_saved_settings()
    else:
        root = tk.Tk(); app = CameraTunerApp(root)
        root.protocol("WM_DELETE_WINDOW", lambda: [app.cap.release(), root.destroy()])
        root.mainloop()
