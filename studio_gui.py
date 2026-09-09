import sys

# --- GLOBAL ENCODING FIX ---
# Force Windows terminal to support UTF-8 emojis without crashing
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
# ---------------------------

import multiprocessing
import social_engine
import cloud_logger
import customtkinter as ctk
from tkinter import colorchooser, filedialog, messagebox, simpledialog
import threading
import sys
import os
import re
import glob
import json
import time
import shutil 
from datetime import datetime
import pystray
from PIL import Image, ImageDraw, ImageTk
import gc
import winreg
import psutil

# --- GLOBAL FFMPEG PATH INJECTION ---
# Forces Windows subprocesses to recognize ffmpeg and ffprobe natively
_ffmpeg_bin_path = r"C:\ffmpeg\bin"
if _ffmpeg_bin_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_bin_path + os.pathsep + os.environ.get("PATH", "")
# ------------------------------------

# --- ABSOLUTE LOCAL ANCHOR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# Migrate settings.json from AppData if it exists there but is missing locally
old_app_data_dir = os.path.join(os.environ.get('APPDATA', ''), 'IslamicReelsStudio')
old_settings_path = os.path.join(old_app_data_dir, 'settings.json')
local_settings_path = os.path.join(BASE_DIR, 'settings.json')

if not os.path.exists(local_settings_path) and os.path.exists(old_settings_path):
    try:
        import shutil
        shutil.copy2(old_settings_path, local_settings_path)
        print("[SYSTEM] Migrated settings.json from AppData to local folder.")
    except Exception as e:
        print(f"[SYSTEM] Warning: Failed to migrate settings.json: {e}")

install_dir = BASE_DIR
creds_vault_dir = os.path.join(install_dir, 'credentials')

LF_TEMP = os.path.join(BASE_DIR, "lf_temp")
LF_OUTPUT = os.path.join(BASE_DIR, "lf_output")
LF_SCRIPTS = os.path.join(BASE_DIR, "lf_scripts")
LF_ASSETS = os.path.join(BASE_DIR, "lf_assets")
LF_BG = os.path.join(BASE_DIR, "bg")

os.makedirs(LF_TEMP, exist_ok=True)
os.makedirs(LF_OUTPUT, exist_ok=True)
os.makedirs(LF_SCRIPTS, exist_ok=True)
os.makedirs(LF_ASSETS, exist_ok=True)
os.makedirs(LF_BG, exist_ok=True)
os.makedirs(creds_vault_dir, exist_ok=True)

# --- DYNAMIC RAM BOOT LOG ---
_mem = psutil.virtual_memory()
_total_gb = round(_mem.total / (1024 ** 3), 1)
_alloc_gb = round(_total_gb * 0.75, 1)
print(f"[+] Dynamic Memory: Total {_total_gb}GB | Allocating {_alloc_gb}GB (75%)")
# ----------------------------

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

SETTINGS_FILE = "settings.json"

CARD_BG = "#212325"
BG_COLOR = "#18191A"

class RedirectText:
    def __init__(self, text_widget, root):
        self.text_widget = text_widget
        self.root = root
        self.terminal = sys.__stdout__
        # Open log file for high-velocity logging in append mode
        self.log_file = open("longform_runtime.log", "a", encoding="utf-8", buffering=1)
        self.buffer = ""

    def write(self, string):
        # 1. Output directly to the terminal stdout
        if self.terminal is not None:
            try:
                self.terminal.write(string)
                self.terminal.flush()
            except Exception:
                pass
        
        # 2. Reroute all velocity prints to log file
        try:
            self.log_file.write(string)
            self.log_file.flush()
        except Exception:
            pass

        # 3. Buffer lines to filter high-level status updates for visual console
        self.buffer += string
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            lower_line = line.lower()
            show_in_gui = False
            
            if any(prefix in line for prefix in ["[+]", "[x]", "[SYSTEM]", "✅", "🎬", "🚀", "[!]", "🎙️", "⏳", "⚡", "🧠", "🔗", "⚙️", "🎵", "📄", "💾", "⚠️", "❌", ">"]):
                show_in_gui = True
            elif any(keyword in lower_line for keyword in ["error", "halted", "pipeline", "initiating", "cooldown", "retrying", "progress", "chunk", "tts", "silero", "whisper", "transcrib", "render", "ffmpeg"]):
                show_in_gui = True
            elif "cycle complete" in lower_line or "logged successful" in lower_line:
                show_in_gui = True
                
            if show_in_gui:
                self.root.after(0, self._update_gui, line + "\n")

    def _update_gui(self, line):
        try:
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", line)
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        except Exception:
            pass

    def flush(self):
        if self.terminal is not None:
            try:
                self.terminal.flush()
            except Exception:
                pass
        try:
            self.log_file.flush()
        except Exception:
            pass

class IslamicReelsStudio(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.is_startup_launch = "--startup" in sys.argv
        
        self.title("YouTube Documentary Studio - Agency Edition by AMB Enterprise")
        self.geometry("920x680") 
        self.configure(fg_color=BG_COLOR) 
        self.resizable(True, True)

        try:
            icon_path = os.path.join(install_dir, "logo.JPG")
            if os.path.exists(icon_path):
                icon_img = ImageTk.PhotoImage(Image.open(icon_path))
                self.wm_iconphoto(True, icon_img)
        except Exception as e:
            print(f"   > ⚠️ Notice: Custom logo.JPG not loaded: {e}")
        
        self.protocol('WM_DELETE_WINDOW', self.hide_window)

        self.creds_lock = threading.Lock()
        self.engine_is_busy = False
        self.is_running = False
        self.engine_thread_active = False
        
        self.master_settings = self.load_settings()
        if not self.master_settings:
            self.master_settings = {"Main Page": self.get_default_profile()}
            self.save_settings()
            
        self.active_profile = list(self.master_settings.keys())[0]
        
        # Probe dynamic system GPU on startup
        self.detected_gpu = self.probe_gpu()
        self.set_active_setting("hardware_profile", self.detected_gpu)
        self.save_settings()
        
        self.stage_credentials(self.active_profile)
        
        self.tray_icon = None

        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(pady=(30, 20), padx=40, fill="x")
        
        self.title_label = ctk.CTkLabel(self.header_frame, text="🎬 YouTube Documentary Studio", font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"))
        self.title_label.pack(side="left")

        self.settings_btn = ctk.CTkButton(self.header_frame, text="🔒 Settings & Profiles", font=ctk.CTkFont(weight="bold"), fg_color="#E67E22", hover_color="#D35400", corner_radius=8, width=170, height=40, command=self.check_password_and_open)
        self.settings_btn.pack(side="right")
        
        disp = getattr(self, "gpu_display_name", "") or self.detected_gpu.upper()
        self.active_display = ctk.CTkLabel(self, text=f"Currently Managing: {self.active_profile} | GPU: {disp} ⚡", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A29BFE")
        self.active_display.pack(pady=(0, 10))

        # Status Uplink Card
        self.status_card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=15)
        self.status_card.pack(pady=15, padx=40, fill="x")
        
        ctk.CTkLabel(self.status_card, text="📡 Server Uplink:", font=ctk.CTkFont(weight="bold", size=13)).pack(side="left", padx=25, pady=15)
        
        self.lbl_yt = ctk.CTkLabel(self.status_card, text="⚪ YouTube", font=ctk.CTkFont(size=13))
        self.lbl_yt.pack(side="left", padx=15)
        self.lbl_discord = ctk.CTkLabel(self.status_card, text="⚪ Discord Bot", font=ctk.CTkFont(size=13))
        self.lbl_discord.pack(side="left", padx=15)
        
        self.lbl_last_post = ctk.CTkLabel(self.status_card, text="☁️ Last Check: ...", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A29BFE")
        self.lbl_last_post.pack(side="left", padx=20)

        self.refresh_btn = ctk.CTkButton(self.status_card, text="🔄 Ping", width=60, height=28, corner_radius=6, fg_color="#3A3E41", hover_color="#4A4E51", command=self.refresh_status_bg)
        self.refresh_btn.pack(side="right", padx=20)

        # Visible GUI Terminal Window
        self.log_textbox = ctk.CTkTextbox(self, width=820, height=200, fg_color="#0D0E0F", text_color="#00FF41", font=("Consolas", 12), corner_radius=10, border_width=1, border_color="#2B2B2B")
        self.log_textbox.pack(pady=10, padx=40, fill="both", expand=True)
        self.log_textbox.configure(state="disabled")
        redirector = RedirectText(self.log_textbox, self)
        sys.stdout = redirector
        sys.stderr = redirector

        # Multi-Stage Task Progress Bar Card with Proceeding Rate Display
        self.upload_card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        self.upload_card.pack(pady=(0, 6), padx=40, fill="x")
        upload_inner = ctk.CTkFrame(self.upload_card, fg_color="transparent")
        upload_inner.pack(fill="x", padx=20, pady=(8, 10))

        # Top row: Task Stage & Proceeding Rate (Left) + Percentage (Right)
        progress_info_row = ctk.CTkFrame(upload_inner, fg_color="transparent")
        progress_info_row.pack(fill="x", pady=(0, 6))

        self.task_progress_label = ctk.CTkLabel(progress_info_row, text="⚡ Task Progress: Idle", font=ctk.CTkFont(weight="bold", size=13), anchor="w")
        self.task_progress_label.pack(side="left", fill="x", expand=True)

        self.upload_pct_label = ctk.CTkLabel(progress_info_row, text="Idle", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A29BFE", anchor="e")
        self.upload_pct_label.pack(side="right")

        # Bottom row: Full-Width Visual Progress Bar
        self.upload_progress_bar = ctk.CTkProgressBar(upload_inner, height=18, corner_radius=9, progress_color="#00D2FF", fg_color="#2B2B2B")
        self.upload_progress_bar.set(0)
        self.upload_progress_bar.pack(fill="x", expand=True)

        # Manual Mode Card: Script & Thumbnail Selection
        self.manual_script_card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        self.manual_script_card.pack(pady=(0, 6), padx=40, fill="x")
        manual_inner = ctk.CTkFrame(self.manual_script_card, fg_color="transparent")
        manual_inner.pack(fill="x", padx=20, pady=(10, 10))

        # Row 1: Manual Script
        script_row = ctk.CTkFrame(manual_inner, fg_color="transparent")
        script_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(script_row, text="📄 Manual Script:", font=ctk.CTkFont(weight="bold", size=13), width=130, anchor="w").pack(side="left")
        self.manual_script_entry = ctk.CTkEntry(script_row, placeholder_text="Select a .txt script file...", font=ctk.CTkFont(size=12))
        self.manual_script_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.manual_script_browse_btn = ctk.CTkButton(
            script_row, text="📁 Browse Script", width=120, height=30,
            corner_radius=8, fg_color="#3A3E41", hover_color="#4A4E51",
            command=self._browse_manual_script
        )
        self.manual_script_browse_btn.pack(side="right")

        # Row 2: Manual Thumbnail Picture
        thumb_row = ctk.CTkFrame(manual_inner, fg_color="transparent")
        thumb_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(thumb_row, text="🖼️ Thumbnail Pic:", font=ctk.CTkFont(weight="bold", size=13), width=130, anchor="w").pack(side="left")
        self.manual_thumb_entry = ctk.CTkEntry(thumb_row, placeholder_text="Select thumbnail picture (.jpg, .png, .webp)...", font=ctk.CTkFont(size=12))
        self.manual_thumb_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.manual_thumb_browse_btn = ctk.CTkButton(
            thumb_row, text="📁 Browse Image", width=120, height=30,
            corner_radius=8, fg_color="#3A3E41", hover_color="#4A4E51",
            command=self._browse_manual_thumbnail
        )
        self.manual_thumb_browse_btn.pack(side="right")

        # Row 3: Instant Render Button
        action_row = ctk.CTkFrame(manual_inner, fg_color="transparent")
        action_row.pack(fill="x", pady=(2, 0))
        self.render_manual_btn = ctk.CTkButton(
            action_row, text="🎬 RENDER MANUAL VIDEO NOW (Script + Thumbnail)",
            height=34, corner_radius=8, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#8E44AD", hover_color="#732D91",
            command=self.trigger_render_manual_now
        )
        self.render_manual_btn.pack(fill="x")

        # Store selected paths as instance variables
        self.manual_script_path = self.get_active_setting("lf_manual_script_path", "")
        if self.manual_script_path:
            self.manual_script_entry.insert(0, self.manual_script_path)
        self.manual_thumbnail_path = self.get_active_setting("lf_manual_thumbnail_path", "")
        if self.manual_thumbnail_path:
            self.manual_thumb_entry.insert(0, self.manual_thumbnail_path)


        # Control and Action Buttons Card
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(pady=(10, 20), padx=40, fill="x")

        self.lbl_countdown = ctk.CTkLabel(self.btn_frame, text="Status: Ready to Render", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F39C12")
        self.lbl_countdown.pack(side="top", pady=(0, 15))

        self.generate_btn = ctk.CTkButton(self.btn_frame, text="🎬 START LONG-FORM AUTOMATION ENGINE", height=50, corner_radius=10, font=ctk.CTkFont(size=16, weight="bold"), command=self.toggle_automation)
        self.generate_btn.pack(side="top", fill="x", pady=(0, 10))

        # Horizontal Row for Manual Gen and Manual Push Buttons
        self.manual_actions_frame = ctk.CTkFrame(self.btn_frame, fg_color="transparent")
        self.manual_actions_frame.pack(fill="x", pady=(0, 10))

        self.manual_lf_btn = ctk.CTkButton(
            self.manual_actions_frame,
            text="🎥 MANUAL LONG-FORM GEN (Force Queue)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=["#FF9F43", "#EE5A24"],
            hover_color=["#F8EFBA", "#EA2027"],
            command=self.trigger_manual_long_form
        )
        self.manual_lf_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.manual_upload_btn = ctk.CTkButton(
            self.manual_actions_frame,
            text="📤 Push Last Render to YouTube",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2980B9",
            hover_color="#1F618D",
            command=self.trigger_manual_last_render_upload
        )
        self.manual_upload_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

        self.populate_main_ui()
        self.refresh_status_bg()
        
        self.update_lf_countdown()
        self.start_discord_listener()
        
        if self.get_active_setting("run_in_background", False):
            print("[SYSTEM] Auto-Launch Enabled! Initializing in 3 seconds...")
            self.after(3000, self.auto_start_check)
            if self.is_startup_launch:
                print("   > 🥷 Booted by Windows Startup. Hiding in System Tray...")
                self.after(100, self.hide_window)

        # Set initial state of the Manual Script browse button
        self.after(200, self.refresh_manual_script_ui)

        # Background pre-warm for Silero Neural TTS and voice tests (Zero-delay Play Test)
        def _prewarm_tts():
            try:
                from silero_manager import get_silero_manager
                mgr = get_silero_manager()
                mgr.preload_models(['ru', 'en'])
                test_dir = os.path.join(LF_TEMP, "test_voices")
                os.makedirs(test_dir, exist_ok=True)
                sample_voices = [
                    ('xenia', 'ru', 'Здравствуйте! Это проверка голоса студии АМБ.'),
                    ('aidar', 'ru', 'Здравствуйте! Это проверка мужского голоса студии АМБ.'),
                    ('xenia', 'en', 'Hello! This is a voice test for AMB Studio.'),
                    ('aidar', 'en', 'Hello! This is a deep voice test for AMB Studio.')
                ]
                for spk, lng, txt in sample_voices:
                    vp = os.path.join(test_dir, f"test_{spk}_{lng}.wav")
                    if not os.path.exists(vp):
                        try:
                            mgr.generate(txt, output_path=vp, speaker=spk, language=lng)
                        except Exception:
                            pass
            except Exception:
                pass
        threading.Thread(target=_prewarm_tts, daemon=True).start()

    def update_task_progress(self, pct, stage_text="Processing..."):
        """Thread-safe multi-stage progress bar updater for TTS, Subtitles, Rendering, and Uploading."""
        def _do_update():
            try:
                frac = max(0.0, min(1.0, pct / 100.0))
                self.upload_progress_bar.set(frac)
                if stage_text:
                    clean_stage = stage_text.lstrip("⚡ ").rstrip(":")
                    self.task_progress_label.configure(text=f"⚡ {clean_stage}:")
                if pct >= 100:
                    self.upload_pct_label.configure(text="✅ 100%", text_color="#2ECC71")
                else:
                    self.upload_pct_label.configure(text=f"{int(pct)}%", text_color="#00D2FF")
            except Exception:
                pass
        self.after(0, _do_update)

    def update_upload_progress(self, pct):
        """Thread-safe progress bar updater — called from the background upload thread."""
        self.update_task_progress(pct, "Upload Progress")
        if pct >= 100:
            self.after(4000, self._reset_upload_bar)

    def _reset_upload_bar(self):
        try:
            self.upload_progress_bar.set(0)
            self.task_progress_label.configure(text="⚡ Task Progress:")
            self.upload_pct_label.configure(text="Idle", text_color="#A29BFE")
        except Exception:
            pass

    def _browse_manual_script(self):
        """Opens a file picker for .txt scripts."""
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="Select Script File",
            filetypes=[("Text Script Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            # Validate that script is not empty
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                if not content:
                    messagebox.showwarning(
                        "Empty Script File",
                        f"The selected file '{os.path.basename(file_path)}' is empty (0 bytes)!\n\n"
                        "Please open it on your Desktop, paste or write your script into it, save it (Ctrl+S), and select it again."
                    )
                    return
            except Exception as e:
                messagebox.showerror("Read Error", f"Could not read script file: {e}")
                return

            self.manual_script_path = file_path
            self.set_active_setting("lf_manual_script_path", file_path)
            self.set_active_setting("lf_manual_script_enabled", True)
            self.save_settings()
            try:
                self.manual_script_entry.delete(0, "end")
                self.manual_script_entry.insert(0, file_path)
            except Exception:
                pass
            print(f"   > 📄 Manual script selected: {file_path}")
            print(f"   > 💡 Script loaded! Select a Thumbnail Picture (optional) and click 'RENDER MANUAL VIDEO NOW'.")

    def _browse_manual_thumbnail(self):
        """Opens a file picker for thumbnail/cover images (.jpg, .jpeg, .png, .webp)."""
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="Select Thumbnail Image",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.webp"), ("All Files", "*.*")]
        )
        if file_path:
            self.manual_thumbnail_path = file_path
            self.set_active_setting("lf_manual_thumbnail_path", file_path)
            self.save_settings()
            try:
                self.manual_thumb_entry.delete(0, "end")
                self.manual_thumb_entry.insert(0, file_path)
            except Exception:
                pass
            print(f"   > 🖼️ Thumbnail picture selected: {file_path}")

    def trigger_render_manual_now(self):
        """Validates manual script + thumbnail and immediately launches video generation."""
        # Read from entry fields in case user typed or pasted directly
        try:
            entry_script = self.manual_script_entry.get().strip()
            if entry_script:
                self.manual_script_path = entry_script
            entry_thumb = self.manual_thumb_entry.get().strip()
            if entry_thumb:
                self.manual_thumbnail_path = entry_thumb
        except Exception:
            pass

        script_path = getattr(self, "manual_script_path", "").strip()
        if not script_path or not os.path.exists(script_path):
            messagebox.showwarning("Missing Script", "Please browse and select a valid .txt script file first!")
            return

        try:
            with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            if not content:
                messagebox.showwarning(
                    "Empty Script File",
                    f"The script file '{os.path.basename(script_path)}' contains no text (0 bytes)!\n\n"
                    "Please open the file on your Desktop, write or paste your script into it, save it (Ctrl+S), and click Render again."
                )
                return
        except Exception as e:
            messagebox.showerror("Read Error", f"Could not read script file: {e}")
            return

        prof_name = self.active_profile
        settings = self.master_settings.get(prof_name, {})
        print(f"\n========================================")
        print(f"🎬 MANUAL TRIGGER: Starting Long-Form Generation for [{prof_name}]...")
        print(f"   > 📄 Script: {os.path.basename(script_path)}")
        thumb_path = getattr(self, "manual_thumbnail_path", "").strip()
        if thumb_path and os.path.exists(thumb_path):
            print(f"   > 🖼️ Thumbnail: {os.path.basename(thumb_path)}")
        else:
            print("   > 🖼️ Thumbnail: Auto-resolving from assets / background video...")
        print(f"========================================")

        import threading
        threading.Thread(
            target=lambda: self.process_long_form_queue(prof_name, settings, force=True, is_manual_script=True),
            daemon=True
        ).start()

    def refresh_manual_script_ui(self):
        """Refreshes manual script & thumbnail UI elements."""
        try:
            is_enabled = self.get_active_setting("lf_manual_script_enabled", True)
            state = "normal"
            self.manual_script_browse_btn.configure(state=state)
            self.manual_script_entry.configure(state=state)
            if hasattr(self, "manual_thumb_browse_btn"):
                self.manual_thumb_browse_btn.configure(state=state)
            if hasattr(self, "manual_thumb_entry"):
                self.manual_thumb_entry.configure(state=state)
            if hasattr(self, "render_manual_btn"):
                self.render_manual_btn.configure(state=state)
        except Exception:
            pass


    def probe_gpu(self):
        device = "cpu"
        self.gpu_display_name = "CPU"
        
        # 1. Probe via nvidia-smi (Official NVIDIA driver CLI - instant & accurate for GTX 1660 Super)
        try:
            import subprocess
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                gpu_name = parts[0]
                vram_mb = parts[1] if len(parts) > 1 else "6144"
                vram_gb = round(float(vram_mb) / 1024, 1) if vram_mb.replace('.', '', 1).isdigit() else 6.0
                device = "cuda"
                self.gpu_display_name = f"{gpu_name} ({vram_gb}GB VRAM - CUDA/NVENC)"
                print(f"[SYSTEM] 🚀 NVIDIA GPU Detected: {gpu_name} ({vram_gb} GB VRAM) | Hardware Acceleration: CUDA & NVENC ACTIVE")
                return device
        except Exception:
            pass

        # 2. Probe via PyTorch CUDA
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                try:
                    vram_bytes = torch.cuda.get_device_properties(0).total_memory
                    vram_gb = round(vram_bytes / (1024 ** 3), 1)
                except Exception:
                    vram_gb = 6.0
                self.gpu_display_name = f"{gpu_name} ({vram_gb}GB VRAM - CUDA/NVENC)"
                print(f"[SYSTEM] 🚀 NVIDIA CUDA Detected: {gpu_name} ({vram_gb} GB VRAM) - Acceleration ACTIVE")
                return device
        except Exception:
            pass

        # 3. Probe via Windows CimInstance VideoController
        try:
            import subprocess
            cmd = "powershell -Command \"Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name\""
            output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                l = line.strip()
                if any(k in l.lower() for k in ["nvidia", "geforce", "gtx", "rtx"]):
                    device = "cuda"
                    vram_str = "6GB" if "1660" in l else "VRAM"
                    self.gpu_display_name = f"{l} ({vram_str} - CUDA/NVENC)"
                    print(f"[SYSTEM] 🚀 NVIDIA GPU Controller Detected: {l} | Hardware Acceleration: CUDA & NVENC ACTIVE")
                    return device
                elif "amd" in l.lower() or "radeon" in l.lower():
                    device = "amf"
                    self.gpu_display_name = f"{l} (AMD AMF)"
                    print(f"[SYSTEM] 🚀 AMD GPU Detected: {l} (AMF Active)")
                    return device
        except Exception:
            pass

        print("[SYSTEM] GPU Probe: No discrete GPU detected. Defaulting to CPU.")
        self.gpu_display_name = "CPU (Software)"
        return device

    def start_discord_listener(self):
        # Determine target token
        token = None
        active_token = self.get_active_setting("discord_bot_token")
        if active_token and active_token.strip() and "YOUR_" not in active_token:
            token = active_token
        else:
            for profile in self.master_settings.values():
                bot_token = profile.get("discord_bot_token")
                if bot_token and bot_token.strip() and "YOUR_" not in bot_token:
                    token = bot_token
                    break

        if not token:
            print("   > ⚠️ Discord Listener: No valid token found in settings profiles.")
            return

        old_client = getattr(self, "discord_client", None)
        if old_client is not None:
            # If the bot is already running with the same token, just reload settings in-place
            old_token = getattr(old_client, "_bot_token", None)
            if old_token == token and hasattr(old_client, "is_ready") and old_client.is_ready():
                print("[SYSTEM] Discord Master Agent is already running and token is unchanged. Reloading settings...")
                old_client.load_settings()
                return
            
            print("[SYSTEM] Stopping existing Discord Master Agent...")
            try:
                loop = old_client.loop
                if loop and loop.is_running():
                    import asyncio
                    asyncio.run_coroutine_threadsafe(old_client.close(), loop)
            except Exception as e:
                print(f"   > ⚠️ Error closing old Discord client: {e}")

        def run_bot(bot_token_to_use):
            try:
                import discord_listener
                print("[SYSTEM] Launching Discord Master Agent in background thread...")
                client = discord_listener.AMBMasterAgent()
                client._bot_token = bot_token_to_use
                self.discord_client = client
                client.run(bot_token_to_use)
            except Exception as e:
                print(f"   > ❌ Discord Listener Thread Error: {e}")
                if getattr(self, "discord_client", None) == client:
                    self.discord_client = None

        threading.Thread(target=run_bot, args=(token,), daemon=True).start()

    def stage_credentials(self, profile_name):
        os.makedirs(os.path.join(creds_vault_dir, profile_name), exist_ok=True)
        prof_dir = os.path.join(creds_vault_dir, profile_name)
        
        for file in ["client_secret.json", "sheets_secret.json"]:
            src = os.path.join(prof_dir, file)
            dst = file 
            if os.path.exists(src):
                shutil.copy2(src, dst)
            else:
                if os.path.exists(dst): os.remove(dst)

    def get_default_profile(self):
        return {
            "admin_password": "ADMIN", 
            "enable_sheet_logs": True, 
            "personal_sheet_url": "", 
            "run_in_background": False,
            
            # Discord Credentials
            "discord_bot_token": "",
            "discord_channel_id": "",
            
            # Groq API Keys Array
            "groq_api_keys": [],
            
            # Long-form Engine Parameters
            "lf_enabled": True,
            "lf_auto_enabled": False,
            "lf_subtitles_enabled": True,
            "lf_upload_interval": 24,
            "lf_custom_length_enabled": False,
            "lf_target_minutes": 60,
            "lf_main_language": "English",
            "lf_subtitle_language": "Arabic",
            "lf_voice_actor": "English (US) Bella (Premium Female)",
            "lf_sub_size": "24",
            "lf_sub_color": "Yellow",
            "lf_sub_position": "Bottom",
            "lf_hardware_mode": "Standard",
            "lf_bg_music": "",
            "lf_bg_music_enabled": True,
            "lf_last_upload_time": 0,
            "hardware_profile": "cpu",
            "lf_metadata_language": "English",
            "lf_manual_script_enabled": False,
            "lf_manual_script_path": ""
        }

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    if "admin_password" in data and not isinstance(data["admin_password"], dict):
                        data = {"Main Page": data}
                    clean_data = {}
                    if isinstance(data, dict):
                        for key, val in data.items():
                            if isinstance(val, dict):
                                clean_data[key] = val
                    if clean_data:
                        return clean_data
            except: pass
        return {}
        
    def save_settings(self):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.master_settings, f, indent=4)

    def get_active_setting(self, key, default=None):
        if not self.active_profile or self.active_profile not in self.master_settings:
            return default
        return self.master_settings[self.active_profile].get(key, default)

    def set_active_setting(self, key, value):
        if self.active_profile and self.active_profile in self.master_settings:
            self.master_settings[self.active_profile][key] = value

    def populate_main_ui(self):
        gpu = self.get_active_setting("hardware_profile", "cpu")
        disp = getattr(self, "gpu_display_name", "")
        if not disp or (gpu != "cuda" and "NVIDIA" in disp):
            disp = gpu.upper()
        self.active_display.configure(text=f"Currently Managing: {self.active_profile} | GPU: {disp} ⚡")
        
        # Keep manual script and thumbnail settings in sync when active profile changes
        self.manual_script_path = self.get_active_setting("lf_manual_script_path", "")
        try:
            self.manual_script_entry.delete(0, "end")
            if self.manual_script_path:
                self.manual_script_entry.insert(0, self.manual_script_path)
        except Exception:
            pass
        self.manual_thumbnail_path = self.get_active_setting("lf_manual_thumbnail_path", "")
        try:
            if hasattr(self, "manual_thumb_entry"):
                self.manual_thumb_entry.delete(0, "end")
                if self.manual_thumbnail_path:
                    self.manual_thumb_entry.insert(0, self.manual_thumbnail_path)
        except Exception:
            pass
        self.refresh_manual_script_ui()

    def backup_keys_to_db(self, profile_name, keys_vals):
        import sqlite3
        try:
            conn = sqlite3.connect("groq_keys_backup.db")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groq_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT,
                    api_key TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("DELETE FROM groq_keys WHERE profile = ?", (profile_name,))
            for key in keys_vals:
                if key.strip():
                    cursor.execute("INSERT INTO groq_keys (profile, api_key) VALUES (?, ?)", (profile_name, key.strip()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"   > ❌ SQLite Backup Error: {e}")

    def update_lf_countdown(self):
        try:
            if self.engine_is_busy:
                status_text = "Status: Engine Busy..."
                color = "#F39C12"
            else:
                status_text = "Status: Ready to Render"
                color = "#2ECC71"
            self.lbl_countdown.configure(text=status_text, text_color=color)
        except Exception:
            pass
        self.after(1000, self.update_lf_countdown)

    def auto_start_check(self):
        any_auto = any(p.get("lf_auto_enabled", False) for p in self.master_settings.values())
        if any_auto: self.toggle_automation()
        else: print("   > ℹ️ Auto-Launch: App started, but Long-Form Automation Loops are OFF. Standing by.")

    def hide_window(self):
        self.withdraw()
        image = Image.new('RGB', (64, 64), color=(46, 204, 113))
        d = ImageDraw.Draw(image)
        d.text((10, 25), "Doc-Bot", fill=(255, 255, 255))
        menu = (pystray.MenuItem('Show Dashboard', self.show_window), pystray.MenuItem('Exit Completely', self.quit_window))
        self.tray_icon = pystray.Icon("DocStudio", image, "YouTube Documentary Studio", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon, item):
        self.tray_icon.stop()
        self.after(1000, self.deiconify)

    def quit_window(self, icon, item):
        self.tray_icon.stop()
        self.destroy()
        os._exit(0) 

    def toggle_windows_startup(self, enable):
        if not getattr(sys, 'frozen', False): return
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "IslamicReelsStudioAgency" # Keep key name for backward compatibility
        exe_path = f'"{sys.executable}" --startup'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable: winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            else:
                try: winreg.DeleteValue(key, app_name)
                except FileNotFoundError: pass 
            winreg.CloseKey(key)
        except Exception: pass

    def check_password_and_open(self):
        dialog = ctk.CTkInputDialog(text="Enter Admin Password:", title="Settings Locked")
        pwd = dialog.get_input()
        first_prof = list(self.master_settings.values())[0] if self.master_settings else {}
        admin_pass = "ADMIN" if isinstance(first_prof, str) else first_prof.get("admin_password", "ADMIN")
        if pwd == admin_pass:
            self.open_settings_window()
        elif pwd is not None:
            messagebox.showerror("Access Denied", "Incorrect Password! Access to Agency Tools is restricted.")

    def refresh_status_bg(self):
        self.lbl_yt.configure(text="🟡 Pinging YT...", text_color="gray")
        self.lbl_discord.configure(text="🟡 Pinging Bot...", text_color="gray")
        self.lbl_last_post.configure(text="🟡 Reading Logs...", text_color="gray")
        threading.Thread(target=self.fetch_and_update_status, daemon=True).start()

    def fetch_and_update_status(self):
        with self.creds_lock:
            self.stage_credentials(self.active_profile)
            
        status = {"youtube": "🔴 Missing client_secret.json"}
        self.last_time = None
        
        try:
            prof_yt_path = os.path.join(creds_vault_dir, self.active_profile, "client_secret.json")
            token_path = os.path.join(creds_vault_dir, self.active_profile, "token.json")
            
            if os.path.exists(prof_yt_path):
                if os.path.exists(token_path):
                    status["youtube"] = "🟢 YT API OK"
                else:
                    status["youtube"] = "🟡 Needs OAuth Sign-in"
            else:
                if os.path.exists("client_secret.json"):
                    status["youtube"] = "🟡 OAuth File Staged"
                else:
                    status["youtube"] = "🔴 Missing Secret"
                    
            lf_log_file = f"lf_last_post_{self.active_profile}.txt"
            if os.path.exists(lf_log_file):
                with open(lf_log_file, "r") as f:
                    self.last_time = datetime.fromisoformat(f.read().strip())
        except Exception:
            status["youtube"] = "🌐 Network / Auth Error"
            self.last_time = None
        
        def update_labels():
            self.lbl_yt.configure(text=status["youtube"], text_color="#2FA572" if "OK" in status["youtube"] else "#D9534F" if "Missing" in status["youtube"] else "gray")

            # Update Discord Bot Status
            bot_client = getattr(self, "discord_client", None)
            if bot_client is not None and bot_client.is_ready():
                self.lbl_discord.configure(text="🟢 Discord Bot OK", text_color="#2FA572")
            elif bot_client is not None and not bot_client.is_closed():
                self.lbl_discord.configure(text="🟡 Discord Sync...", text_color="gray")
            else:
                self.lbl_discord.configure(text="🔴 Discord Offline", text_color="#D9534F")
                
            if self.last_time:
                time_str = self.last_time.strftime("%Y-%m-%d %I:%M %p")
                self.lbl_last_post.configure(text=f"☁️ Last Upload: {time_str}", text_color="#2CC985")
            else:
                self.lbl_last_post.configure(text="☁️ Last Upload: None", text_color="#F39C12")

        self.after(0, update_labels)

    def scan_fonts(self):
        if not os.path.exists("font"): os.makedirs("font")
        font_files = glob.glob("font/*.ttf")
        if not font_files: return ["Default Windows Font (Arial/Tahoma)"]
        return [os.path.basename(f) for f in font_files]

    def switch_settings_profile(self, name, window):
        self.active_profile = name
        self.stage_credentials(name)
        
        # Re-probe hardware for new active profile
        self.detected_gpu = self.probe_gpu()
        self.set_active_setting("hardware_profile", self.detected_gpu)
        self.save_settings()
        
        self.populate_main_ui()
        self.refresh_status_bg()
        
        window.withdraw()
        self.after(200, window.destroy)
        self.after(250, self.open_settings_window)

    def create_new_profile_ui(self, window):
        dialog = ctk.CTkInputDialog(text="Enter New Agency Profile Name:", title="New Profile")
        name = dialog.get_input()
        if name and name.strip():
            name = name.strip()
            if name in self.master_settings:
                messagebox.showerror("Error", "Profile name already exists!")
                return
            self.master_settings[name] = self.get_default_profile()
            self.save_settings()
            self.switch_settings_profile(name, window)
            
    def delete_profile_ui(self, window):
        if len(self.master_settings) <= 1:
            messagebox.showerror("Error", "You cannot delete the last remaining profile in the agency.")
            return
            
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to completely delete the profile '{self.active_profile}'?"):
            del self.master_settings[self.active_profile]
            self.save_settings()
            new_active = list(self.master_settings.keys())[0]
            self.switch_settings_profile(new_active, window)

    def open_settings_window(self):
        settings_win = ctk.CTkToplevel(self)
        settings_win.title("Agency Automation Settings")
        settings_win.geometry("800x750") 
        settings_win.configure(fg_color=BG_COLOR)
        settings_win.attributes("-topmost", True)
        settings_win.grab_set() 
        
        top_bar = ctk.CTkFrame(settings_win, fg_color=CARD_BG, corner_radius=10)
        top_bar.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(top_bar, text="🏢 Agency Profiles", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=15, pady=15)

        profile_scroll = ctk.CTkScrollableFrame(top_bar, orientation="horizontal", height=50, fg_color="transparent")
        profile_scroll.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        
        for p_name in self.master_settings.keys():
            color = "#E67E22" if p_name == self.active_profile else "#3A3E41"
            btn = ctk.CTkButton(profile_scroll, text=p_name, fg_color=color, corner_radius=20, width=100, 
                                command=lambda n=p_name: self.switch_settings_profile(n, settings_win))
            btn.pack(side="left", padx=5)

        ctk.CTkButton(top_bar, text="- Delete", fg_color="#E74C3C", hover_color="#C0392B", width=60, command=lambda: self.delete_profile_ui(settings_win)).pack(side="right", padx=(5, 15))
        ctk.CTkButton(top_bar, text="+ New", fg_color="#27AE60", hover_color="#1E8449", width=60, command=lambda: self.create_new_profile_ui(settings_win)).pack(side="right", padx=5)

        bottom_action_frame = ctk.CTkFrame(settings_win, fg_color="transparent")
        bottom_action_frame.pack(side="bottom", fill="x", pady=(10, 20))

        tabview = ctk.CTkTabview(settings_win, width=650, height=550, fg_color=CARD_BG)
        tabview.pack(padx=20, pady=10, fill="both", expand=True)

        tabview.add("General & Integration")
        tabview.add("YouTube API OAuth")
        tabview.add("Long-Form Engine")
        
        def make_entry(parent, label_text, dict_key, is_password=False):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(pady=8, fill="x")
            ctk.CTkLabel(f, text=label_text, width=140, anchor="w").pack(side="left")
            e = ctk.CTkEntry(f, show="*" if is_password else "")
            e.insert(0, self.get_active_setting(dict_key, ""))
            e.pack(side="right", fill="x", expand=True)
            return e

        # ==========================================
        # --- TAB 1: GENERAL & INTEGRATION ---
        # ==========================================
        gen_frame = ctk.CTkScrollableFrame(tabview.tab("General & Integration"), fg_color="transparent")
        gen_frame.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(gen_frame, text="System Operation", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 5))
        bg_var = ctk.BooleanVar(value=self.get_active_setting("run_in_background", False))
        bg_switch = ctk.CTkSwitch(gen_frame, text="Start with Windows (Auto-Launch hidden in Tray)", variable=bg_var)
        bg_switch.pack(anchor="w", pady=5)

        ctk.CTkLabel(gen_frame, text="Stateless Cloud Logging (Google Sheets)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        sheet_url_entry = make_entry(gen_frame, "Google Sheet URL:", "personal_sheet_url")

        sheet_log_row = ctk.CTkFrame(gen_frame, fg_color="transparent")
        sheet_log_row.pack(fill="x", pady=5)
        sheet_log_var = ctk.BooleanVar(value=self.get_active_setting("enable_sheet_logs", True))
        sheet_log_switch = ctk.CTkSwitch(sheet_log_row, text="Enable Google Sheets Background Logging", variable=sheet_log_var)
        sheet_log_switch.pack(anchor="w", padx=10)
        
        sh_row = ctk.CTkFrame(gen_frame, fg_color="transparent")
        sh_row.pack(fill="x", pady=8)
        ctk.CTkLabel(sh_row, text="Service JSON File:", width=130, anchor="w").pack(side="left")
        
        prof_sheet_path = os.path.join(creds_vault_dir, self.active_profile, "sheets_secret.json")
        sh_status = "✅ Active" if os.path.exists(prof_sheet_path) else "❌ Missing"
        sh_color = "#27AE60" if os.path.exists(prof_sheet_path) else "#E74C3C"
        sh_status_label = ctk.CTkLabel(sh_row, text=sh_status, text_color=sh_color, font=ctk.CTkFont(weight="bold"))
        sh_status_label.pack(side="left", padx=10)

        def install_sh_json():
            file = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
            if file:
                try:
                    os.makedirs(os.path.dirname(prof_sheet_path), exist_ok=True)
                    shutil.copy(file, "sheets_secret.json")
                    shutil.copy(file, prof_sheet_path)
                    sh_status_label.configure(text="✅ Active", text_color="#27AE60")
                    messagebox.showinfo("Sheets Linked", "Service Account JSON installed successfully for this profile!")
                except Exception as e:
                    messagebox.showerror("Install Error", f"Failed to install JSON:\n{e}")

        ctk.CTkButton(sh_row, text="📁 Browse & Install", fg_color="#F39C12", hover_color="#D68910", width=140, command=install_sh_json).pack(side="right")

        ctk.CTkLabel(gen_frame, text="Security & Global Profile Settings", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(15, 5))
        admin_password_entry = make_entry(gen_frame, "Admin Password:", "admin_password", is_password=True)
        
        ctk.CTkLabel(gen_frame, text="Discord Master Agent Integration", font=ctk.CTkFont(weight="bold"), text_color="#A29BFE").pack(anchor="w", pady=(15, 5))
        discord_bot_token_entry = make_entry(gen_frame, "Discord Bot Token:", "discord_bot_token", is_password=True)
        discord_channel_id_entry = make_entry(gen_frame, "Target Channel ID:", "discord_channel_id")

        # ==========================================
        # --- TAB 2: YOUTUBE API OAUTH & GROQ ---
        # ==========================================
        yt_frame = ctk.CTkFrame(tabview.tab("YouTube API OAuth"), fg_color="transparent")
        yt_frame.pack(fill="both", expand=True, pady=10)
        
        ctk.CTkLabel(yt_frame, text="Google OAuth Credentials for YouTube Upload", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(10, 5))
        
        yt_row = ctk.CTkFrame(yt_frame, fg_color="transparent")
        yt_row.pack(fill="x", pady=10)
        ctk.CTkLabel(yt_row, text="OAuth JSON File:", width=130, anchor="w").pack(side="left")
        
        prof_yt_path = os.path.join(creds_vault_dir, self.active_profile, "client_secret.json")
        yt_status = "✅ Installed" if os.path.exists(prof_yt_path) else "❌ Missing"
        yt_color = "#27AE60" if os.path.exists(prof_yt_path) else "#E74C3C"
        yt_status_label = ctk.CTkLabel(yt_row, text=yt_status, text_color=yt_color, font=ctk.CTkFont(weight="bold"))
        yt_status_label.pack(side="left", padx=10)

        def install_yt_json():
            file = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
            if file:
                try:
                    os.makedirs(os.path.dirname(prof_yt_path), exist_ok=True)
                    shutil.copy(file, "client_secret.json")
                    shutil.copy(file, prof_yt_path)
                    yt_status_label.configure(text="✅ Installed", text_color="#27AE60")
                    messagebox.showinfo("YouTube Unlocked", "YouTube OAuth JSON installed successfully for this profile!")
                except Exception as e:
                    messagebox.showerror("Install Error", f"Failed to install JSON:\n{e}")

        ctk.CTkButton(yt_row, text="📁 Browse & Install", fg_color="#C0392B", hover_color="#922B21", width=140, command=install_yt_json).pack(side="right")

        # Scrollable Groq keys list in Tab 2
        ctk.CTkLabel(yt_frame, text="🔑 Groq API Keys (Paste one key per line for auto-rotation):", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(20, 5))
        
        yt_keys_textbox = ctk.CTkTextbox(yt_frame, height=180, fg_color="#0D0E0F", text_color="#00FF41", font=("Consolas", 12), corner_radius=10, border_width=1, border_color="#2B2B2B")
        yt_keys_textbox.pack(fill="both", expand=True, pady=(0, 10))
        
        # Populate textbox with active profile keys
        groq_keys = self.get_active_setting("groq_api_keys", [])
        if isinstance(groq_keys, str):
            groq_keys = [k.strip() for k in groq_keys.split(",") if k.strip()]
        yt_keys_textbox.insert("1.0", "\n".join(groq_keys))

        # ==========================================
        # --- TAB 3: LONG-FORM ENGINE ---
        # ==========================================
        lf_frame = ctk.CTkScrollableFrame(tabview.tab("Long-Form Engine"), fg_color="transparent")
        lf_frame.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(lf_frame, text="Video Generation & Automation Controls", font=ctk.CTkFont(weight="bold"), text_color="#F39C12").pack(anchor="w", pady=(5, 5))
        
        lf_toggle_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_toggle_row.pack(fill="x", pady=5)
        
        lf_auto_var = ctk.BooleanVar(value=self.get_active_setting("lf_auto_enabled", True))
        ctk.CTkSwitch(lf_toggle_row, text="Enable Queue Automation Engine", variable=lf_auto_var).pack(side="left", padx=10)

        lf_sub_toggle_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_sub_toggle_row.pack(fill="x", pady=5)
        lf_subtitles_var = ctk.BooleanVar(value=self.get_active_setting("lf_subtitles_enabled", True))
        ctk.CTkSwitch(lf_sub_toggle_row, text="Enable Subtitles", variable=lf_subtitles_var).pack(side="left", padx=10)

        # New Background Music Enable switch
        lf_bg_music_enabled_var = ctk.BooleanVar(value=self.get_active_setting("lf_bg_music_enabled", True))
        ctk.CTkSwitch(lf_sub_toggle_row, text="Enable Background Music Overlay", variable=lf_bg_music_enabled_var).pack(side="left", padx=10)

        # Manual Script Mode toggle
        lf_manual_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_manual_row.pack(fill="x", pady=5)
        lf_manual_script_var = ctk.BooleanVar(value=self.get_active_setting("lf_manual_script_enabled", False))
        ctk.CTkSwitch(
            lf_manual_row,
            text="📄 Manual Script Mode  ← When ON: Browse button activates on dashboard. Groq generation is skipped.",
            variable=lf_manual_script_var,
            text_color="#F39C12"
        ).pack(side="left", padx=10)

        lf_upl_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_upl_row.pack(fill="x", pady=10)
        ctk.CTkLabel(lf_upl_row, text="Post Interval (Hrs):").pack(side="left", padx=(10, 10))
        lf_interval_var = ctk.StringVar(value=str(self.get_active_setting("lf_upload_interval", 24)))
        ctk.CTkOptionMenu(lf_upl_row, variable=lf_interval_var, values=[str(i) for i in range(1, 73)], width=80).pack(side="left")

        # Direct Target Duration Input
        lf_length_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_length_row.pack(fill="x", pady=5)
        ctk.CTkLabel(lf_length_row, text="Target Video Duration (Minutes):", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(10, 5))
        lf_target_minutes_var = ctk.StringVar(value=str(self.get_active_setting("lf_target_minutes", 2)))
        lf_target_minutes_entry = ctk.CTkEntry(lf_length_row, textvariable=lf_target_minutes_var, width=80)
        lf_target_minutes_entry.pack(side="left", padx=5)
        ctk.CTkLabel(lf_length_row, text="← Enter exact minutes (e.g. 2 for 2-min video, 60 for 1-hour video)", font=ctk.CTkFont(size=11), text_color="#888").pack(side="left", padx=(10, 0))

        # Voice Actor Dropdown (pre-defined for dynamic callback setup)
        voice_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        voice_row.pack(fill="x", pady=10)
        
        ctk.CTkLabel(voice_row, text="Voice Actor (TTS):").pack(side="left", padx=(10, 5))
        lf_voice_actor_var = ctk.StringVar(value=self.get_active_setting("lf_voice_actor", "English (US) Bella (Premium Female)"))
        lf_voice_actor_menu = ctk.CTkOptionMenu(voice_row, variable=lf_voice_actor_var, values=[], width=220)
        lf_voice_actor_menu.pack(side="left", padx=5)

        def play_test_voice():
            voice_actor = lf_voice_actor_var.get()
            profile_lang = self.get_active_setting("lf_main_language", "Russian")
            print(f"[SYSTEM] ▶ Playing voice test for: '{voice_actor}' (Language: {profile_lang})")
            
            def play_thread():
                try:
                    from silero_manager import sync_generate_silero
                    from audio_generator import VOICE_ACTORS
                    speaker = VOICE_ACTORS.get(voice_actor, "xenia")
                    
                    is_ru = profile_lang.lower() in ["russian", "ru"]
                    test_lang = "ru" if is_ru else "en"
                    test_text = "Здравствуйте! Это проверка голоса студии АМБ." if is_ru else "Hello! This is a voice test for AMB Studio."
                    
                    test_dir = os.path.join(LF_TEMP, "test_voices")
                    os.makedirs(test_dir, exist_ok=True)
                    test_path = os.path.join(test_dir, f"test_{speaker}_{test_lang}.wav")
                    
                    # Zero-delay playback: If already synthesized, play immediately!
                    if not os.path.exists(test_path) or os.path.getsize(test_path) == 0:
                        sync_generate_silero(test_text, speaker=speaker, output_path=test_path, sample_rate=48000, language=test_lang)
                    
                    import winsound
                    winsound.PlaySound(test_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                except Exception as e:
                    print(f"   > ❌ Voice Test Error: {e}")
                    
            threading.Thread(target=play_thread, daemon=True).start()

        ctk.CTkButton(
            voice_row, text="▶ Play Test", width=90, height=28,
            corner_radius=6, fg_color="#2ECC71", hover_color="#27AE60",
            command=play_test_voice
        ).pack(side="left", padx=5)

        # Silero Neural Voices
        PREMIUM_VOICES_POOL = [
            "Xenia (Default Female)",
            "Baya (Warm Female)",
            "Kseniya (Clear Female)",
            "Aidar (Deep Male)",
            "Eugene (Calm Male)"
        ]

        VOICE_ACTORS_BY_LANG = {
            "English": PREMIUM_VOICES_POOL,
            "German": PREMIUM_VOICES_POOL,
            "Russian": PREMIUM_VOICES_POOL,
            "Arabic": PREMIUM_VOICES_POOL,
            "Urdu": PREMIUM_VOICES_POOL
        }

        def update_voice_menu(selected_lang):
            voices = VOICE_ACTORS_BY_LANG.get(selected_lang, ["English (US) Bella (Premium Female)"])
            lf_voice_actor_menu.configure(values=voices)
            current_voice = lf_voice_actor_var.get()
            if current_voice not in voices:
                lf_voice_actor_var.set(voices[0])

        # Video Localization Dropdowns
        lang_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lang_row.pack(fill="x", pady=10)
        
        ctk.CTkLabel(lang_row, text="Video Language:").pack(side="left", padx=(10, 5))
        lf_main_lang_var = ctk.StringVar(value=self.get_active_setting("lf_main_language", "English"))
        
        lf_main_lang_menu = ctk.CTkOptionMenu(
            lang_row, 
            variable=lf_main_lang_var, 
            values=["English", "German", "Russian", "Arabic", "Urdu"], 
            width=110,
            command=update_voice_menu
        )
        lf_main_lang_menu.pack(side="left", padx=5)

        ctk.CTkLabel(lang_row, text="Sub Language:").pack(side="left", padx=(15, 5))
        lf_sub_lang_var = ctk.StringVar(value=self.get_active_setting("lf_subtitle_language", "Arabic"))
        ctk.CTkOptionMenu(lang_row, variable=lf_sub_lang_var, values=["Arabic", "English", "German", "Russian", "Urdu", "None"], width=110).pack(side="left", padx=5)

        # Title & Description Language Dropdown
        meta_lang_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        meta_lang_row.pack(fill="x", pady=10)
        ctk.CTkLabel(meta_lang_row, text="Title & Description Language:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(10, 5))
        lf_metadata_lang_var = ctk.StringVar(value=self.get_active_setting("lf_metadata_language", "English"))
        ctk.CTkOptionMenu(
            meta_lang_row,
            variable=lf_metadata_lang_var,
            values=["English", "Arabic", "German", "Russian", "Urdu"],
            width=140
        ).pack(side="left", padx=5)
        ctk.CTkLabel(meta_lang_row, text="← AI generates title, description & hashtags in this language", font=ctk.CTkFont(size=11), text_color="#888").pack(side="left", padx=(10, 0))

        # Trigger dynamic population initially
        update_voice_menu(lf_main_lang_var.get())
        initial_voice = self.get_active_setting("lf_voice_actor", "English (US) Male")
        if initial_voice in VOICE_ACTORS_BY_LANG.get(lf_main_lang_var.get(), []):
            lf_voice_actor_var.set(initial_voice)

        # Advanced Subtitle Customization (Size, Color, Position)
        sub_style_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        sub_style_row.pack(fill="x", pady=10)
        
        ctk.CTkLabel(sub_style_row, text="Sub Size:").pack(side="left", padx=(10, 5))
        self.lf_sub_size_var = ctk.StringVar(value=str(self.get_active_setting("lf_sub_size", "24")))
        # Expanded values to include smaller sizes (12, 14, 16)
        ctk.CTkOptionMenu(sub_style_row, variable=self.lf_sub_size_var, values=["12", "14", "16", "18", "20", "24", "28", "32", "36", "40"], width=80).pack(side="left", padx=5)

        ctk.CTkLabel(sub_style_row, text="Sub Color:").pack(side="left", padx=(15, 5))
        self.lf_sub_color_var = ctk.StringVar(value=self.get_active_setting("lf_sub_color", "Yellow"))
        ctk.CTkOptionMenu(sub_style_row, variable=self.lf_sub_color_var, values=["Yellow", "White", "Green", "Cyan"], width=90).pack(side="left", padx=5)

        ctk.CTkLabel(sub_style_row, text="Sub Position:").pack(side="left", padx=(15, 5))
        self.lf_sub_position_var = ctk.StringVar(value=self.get_active_setting("lf_sub_position", "Bottom"))
        ctk.CTkOptionMenu(sub_style_row, variable=self.lf_sub_position_var, values=["Bottom", "Top", "Center"], width=100).pack(side="left", padx=5)

        style_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        style_row.pack(fill="x", pady=10)
        ctk.CTkLabel(style_row, text="Script Style:").pack(side="left", padx=(10, 5))
        lf_style_var = ctk.StringVar(value=self.get_active_setting("lf_script_style", "Deep Emotional"))
        ctk.CTkOptionMenu(style_row, variable=lf_style_var, values=["Deep Emotional", "Book Reading", "Historical Fact", "Tafseer Explanation", "Russian Story (High Retention)", "Family Drama (High Retention)"], width=260).pack(side="left", padx=5)

        hw_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        hw_row.pack(fill="x", pady=10)
        ctk.CTkLabel(hw_row, text="Hardware Power Mode:").pack(side="left", padx=(10, 5))
        lf_hw_mode_var = ctk.StringVar(value=self.get_active_setting("lf_hardware_mode", "Standard"))
        ctk.CTkOptionMenu(hw_row, variable=lf_hw_mode_var, values=["Low-End PC (Fastest)", "Standard", "High-End Workstation"], width=200).pack(side="left", padx=5)

        ctk.CTkLabel(lf_frame, text="Audio & Acoustics", font=ctk.CTkFont(weight="bold"), text_color="#00D2FF").pack(anchor="w", pady=(20, 5))
        lf_music_row = ctk.CTkFrame(lf_frame, fg_color="transparent")
        lf_music_row.pack(fill="x", pady=5)
        ctk.CTkLabel(lf_music_row, text="Background Music:").pack(side="left", padx=(10, 5))
        lf_music_entry = ctk.CTkEntry(lf_music_row, width=200, placeholder_text="Browse audio/video for looping...")
        lf_music_entry.insert(0, self.get_active_setting("lf_bg_music", ""))
        lf_music_entry.pack(side="left", expand=True, fill="x", padx=5)
        
        def browse_lf_music():
            file = filedialog.askopenfilename(filetypes=[
                ("Audio/Video Files", "*.mp3 *.wav *.m4a *.mp4 *.mkv *.mov *.avi"),
                ("Audio Files", "*.mp3 *.wav *.m4a"),
                ("Video Files", "*.mp4 *.mkv *.mov *.avi")
            ])
            if file:
                lf_music_entry.delete(0, 'end')
                lf_music_entry.insert(0, file)
                
        ctk.CTkButton(lf_music_row, text="📁 Browse", width=80, fg_color="#3A3E41", hover_color="#4A4E51", command=browse_lf_music).pack(side="right", padx=10)

        def save_and_close():
            self.set_active_setting("enable_sheet_logs", sheet_log_var.get())
            self.set_active_setting("run_in_background", bg_var.get())
            self.set_active_setting("personal_sheet_url", sheet_url_entry.get())
            self.set_active_setting("admin_password", admin_password_entry.get())
            self.set_active_setting("discord_bot_token", discord_bot_token_entry.get())
            self.set_active_setting("discord_channel_id", discord_channel_id_entry.get())
            
            # --- SAVE GROQ KEYS ---
            keys_text = yt_keys_textbox.get("1.0", "end-1c")
            groq_keys_list = [k.strip() for k in keys_text.split("\n") if k.strip()]
            self.set_active_setting("groq_api_keys", groq_keys_list)
            self.backup_keys_to_db(self.active_profile, groq_keys_list)
            
            # --- LONG FORM SAVES ---
            self.set_active_setting("lf_enabled", True)
            self.set_active_setting("lf_auto_enabled", lf_auto_var.get())
            self.set_active_setting("lf_subtitles_enabled", lf_subtitles_var.get())
            self.set_active_setting("lf_bg_music_enabled", lf_bg_music_enabled_var.get())
            try:
                minutes_val = int(lf_target_minutes_entry.get().strip())
            except ValueError:
                minutes_val = 2
            self.set_active_setting("lf_target_minutes", minutes_val)
            self.set_active_setting("lf_upload_interval", int(lf_interval_var.get()))
            self.set_active_setting("lf_main_language", lf_main_lang_var.get())
            self.set_active_setting("lf_subtitle_language", lf_sub_lang_var.get())
            self.set_active_setting("lf_voice_actor", lf_voice_actor_var.get())
            self.set_active_setting("lf_sub_size", self.lf_sub_size_var.get())
            self.set_active_setting("lf_sub_color", self.lf_sub_color_var.get())
            self.set_active_setting("lf_sub_position", self.lf_sub_position_var.get())
            self.set_active_setting("lf_script_style", lf_style_var.get())
            self.set_active_setting("lf_bg_music", lf_music_entry.get())
            self.set_active_setting("lf_hardware_mode", lf_hw_mode_var.get())
            self.set_active_setting("lf_metadata_language", lf_metadata_lang_var.get())
            self.set_active_setting("lf_manual_script_enabled", lf_manual_script_var.get())
            # Refresh the Browse button state on the main dashboard after saving
            self.after(100, self.refresh_manual_script_ui)
            
            self.save_settings()
            self.start_discord_listener()
            self.refresh_status_bg() 
            print(f"   > ⚙️ Agency Settings for [{self.active_profile}] Saved Successfully!")

            self.toggle_windows_startup(self.get_active_setting("run_in_background", False))

            is_currently_running = getattr(self, 'is_running', False)
            any_auto = any(p.get("lf_auto_enabled", False) for p in self.master_settings.values())
            
            if any_auto and not is_currently_running:
                print("[SYSTEM] Automation Loop enabled in settings. Auto-Starting Engine...")
                self.toggle_automation()
            elif not any_auto and is_currently_running:
                print("[SYSTEM] Automation Loop disabled across all profiles. Halting Engine...")
                self.toggle_automation()

            settings_win.withdraw()
            settings_win.after(200, settings_win.destroy)

        ctk.CTkButton(bottom_action_frame, text="Save Profile Settings", height=45, corner_radius=10, font=ctk.CTkFont(weight="bold"), command=save_and_close).pack(fill="x", padx=100)

    def toggle_automation(self):
        if getattr(self, 'engine_thread_active', False):
            self.is_running = False
            self.engine_thread_active = False
            self.generate_btn.configure(text="🎬 START LONG-FORM AUTOMATION ENGINE", fg_color=["#2CC985", "#2FA572"], hover_color=["#209661", "#22855A"])
            print("\n[SYSTEM] Stop Command Received: Halting all render and upload processes...")
        else:
            self.is_running = True
            self.engine_thread_active = True
            self.generate_btn.configure(text="🛑 STOP AUTOMATION ENGINE", fg_color="#D9534F", hover_color="#C9302C")
            self.log_textbox.configure(state="normal")
            self.log_textbox.delete("1.0", "end") 
            self.log_textbox.configure(state="disabled")
            threading.Thread(target=self.run_pipeline, daemon=True).start()

    def process_long_form_queue(self, prof_name, settings, force=False, force_queue=False, is_manual_script=False):
        import os
        if not force and not force_queue and not settings.get("lf_enabled", True):
            return False

        manual_path = getattr(self, "manual_script_path", "").strip()
        if not manual_path:
            manual_path = settings.get("lf_manual_script_path", "").strip()

        manual_thumb = getattr(self, "manual_thumbnail_path", "").strip()
        if not manual_thumb:
            manual_thumb = settings.get("lf_manual_thumbnail_path", "").strip()

        queue_file = os.path.join(install_dir, "lf_queues", f"queue_{prof_name.replace(' ', '_')}.json")
        queue_data = []
        if os.path.exists(queue_file):
            try: 
                with open(queue_file, "r") as f:
                    queue_data = json.load(f)
            except Exception:
                queue_data = []

        # If user clicked the orange button (force_queue=True) and current profile queue is empty,
        # scan if any other profile has pending queue items!
        if force_queue and not queue_data:
            for alt_prof, alt_settings in self.master_settings.items():
                if alt_prof == prof_name:
                    continue
                alt_qf = os.path.join(install_dir, "lf_queues", f"queue_{alt_prof.replace(' ', '_')}.json")
                if os.path.exists(alt_qf):
                    try:
                        with open(alt_qf, "r") as f:
                            alt_data = json.load(f)
                            if alt_data and len(alt_data) > 0:
                                print(f"   > 🔀 [Force Queue] Active profile [{prof_name}] queue is empty. Switching to [{alt_prof}] queue ({len(alt_data)} pending items).")
                                prof_name = alt_prof
                                settings = alt_settings
                                queue_file = alt_qf
                                queue_data = alt_data
                                break
                    except Exception:
                        pass

        is_manual_job = False
        should_run_manual = False

        if is_manual_script:
            # Explicit trigger from Purple Button: "RENDER MANUAL VIDEO NOW"
            if manual_path and os.path.exists(manual_path):
                should_run_manual = True
            else:
                print(f"   > ⚠️ [Manual Script Engine] No valid manual script file found at '{manual_path}'.")
                return False
        elif force_queue:
            # Explicit trigger from Orange Button: "MANUAL LONG-FORM GEN (Force Queue)"
            # STRICT RULE: Must generate whatever is in pending queue!
            if queue_data:
                should_run_manual = False
            elif manual_path and os.path.exists(manual_path):
                print(f"   > ℹ️ [Force Queue] Queue is empty. Falling back to selected manual script: '{os.path.basename(manual_path)}'...")
                should_run_manual = True
            else:
                print(f"\n   > ⚠️ [Force Queue] Queue is empty for profile '{prof_name}' and no manual script is selected.")
                return False
        elif force:
            # Generic force trigger
            if queue_data:
                should_run_manual = False
            elif manual_path and os.path.exists(manual_path):
                should_run_manual = True
            else:
                print(f"\n   > ⚠️ [Force Gen] Queue is empty for profile '{prof_name}' and no manual script is selected.")
                return False
        else:
            # Automated scan from run_pipeline
            # NEVER allow manual scripts to hijack pending Discord queue items!
            if queue_data:
                should_run_manual = False
            elif settings.get("lf_manual_script_enabled", False) and manual_path and os.path.exists(manual_path) and prof_name == self.active_profile:
                should_run_manual = True
            else:
                return False

        if should_run_manual:
            script_basename = os.path.splitext(os.path.basename(manual_path))[0]
            script_title = script_basename.replace("_", " ").replace("-", " ")
            
            # Resolve thumbnail: 1. User selected thumbnail 2. candidate images in lf_assets/bg/root 3. cover.jpg
            chosen_img = ""
            if manual_thumb and os.path.exists(manual_thumb):
                chosen_img = manual_thumb
            else:
                candidate_images = []
                for search_d in ["lf_assets", "bg", ""]:
                    dp = os.path.join(install_dir, search_d) if search_d else install_dir
                    if os.path.exists(dp):
                        candidate_images.extend([
                            os.path.join(dp, f) for f in os.listdir(dp)
                            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                        ])
                chosen_img = candidate_images[0] if candidate_images else os.path.join(install_dir, "cover.jpg")
            
            queue_data = [{
                "title": script_title,
                "image_path": chosen_img,
                "prompt": script_title,
                "is_manual_job": True
            }]
            is_manual_job = True
            print(f"   > 📄 [Manual Script Engine] Processing script: '{os.path.basename(manual_path)}' with thumbnail '{os.path.basename(chosen_img)}' for [{prof_name}]...")
        else:
            is_manual_job = False

        if not queue_data:
            return False

        # Check duplication ledger first
        item = queue_data[0]
        title = item.get("title", "").strip()
        if not title:
            title = f"Video_{int(time.time())}"
        image_path = item.get("image_path", "").strip()
        if item.get("is_manual_job"):
            is_manual_job = True

        history_file = os.path.join(install_dir, "lf_published_history.txt")
        if not is_manual_job and not force and not force_queue and os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history = [line.strip().lower() for line in f.readlines() if line.strip()]
                if title.lower() in history:
                    clean_safe = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(' ', '_')
                    existing_vid = os.path.join(install_dir, "lf_output", f"Final_LF_{clean_safe}.mp4")
                    if os.path.exists(existing_vid):
                        print(f"   > ⚠️ Duplicate Title Detected: '{title}' is in published history & video exists. Skipping.")
                        queue_data.pop(0)
                        with open(queue_file, "w") as f:
                            json.dump(queue_data, f, indent=4)
                        return True
                    else:
                        print(f"   > ℹ️ Title '{title}' was in published history, but no rendered video found in lf_output. Re-rendering...")
            except Exception as e:
                print(f"   > ⚠️ Warning: Failed to read published history ledger: {e}")

        interval_hrs = settings.get("lf_upload_interval", 1)
        lf_log_file = os.path.join(install_dir, f"lf_last_post_{prof_name}.txt")
        
        if not force and not force_queue and not is_manual_job and os.path.exists(lf_log_file):
            with open(lf_log_file, "r") as f:
                try: 
                    last_time = datetime.fromisoformat(f.read().strip())
                    delta_hrs = (datetime.now() - last_time).total_seconds() / 3600
                    if delta_hrs < interval_hrs:
                        remaining_mins = int((interval_hrs - delta_hrs) * 60)
                        print(f"   > ⏳ [{prof_name}] Interval timer active. Next scheduled run in: {remaining_mins} minute(s).")
                        return False # Not enough time has passed yet
                except: pass
        elif force or force_queue:
            print(f"   > ⚡ [Force Override] Upload interval timer BYPASSED — starting generation immediately!")

        if not os.path.isabs(image_path):
            abs_image_path = os.path.join(install_dir, image_path)
            if os.path.exists(abs_image_path):
                image_path = abs_image_path
        
        if self.engine_is_busy:
            print(f"   > ⚠️ Engine is busy rendering. Skipping current invocation.")
            return False

        self.engine_is_busy = True
        try:
            print(f"\n========================================")
            print(f"🎬 INITIATING LONG-FORM ENGINE: [{prof_name}]")
            print(f"🎬 Target: {title}")
            print(f"========================================")
            
            from script_generator import LongFormScripter
            import long_form_composer
            import asyncio
            
            # Smart Resume naming derived from sanitized video title (preserves unicode / Cyrillic)
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(' ', '_')
            if not safe_title:
                safe_title = f"video_{int(time.time())}"
            script_file = os.path.join(install_dir, "lf_scripts", f"{safe_title}.txt")
            audio_out = os.path.join(install_dir, "lf_temp", f"voice_{safe_title}.mp3")
            srt_out = os.path.join(install_dir, "lf_temp", f"subs_{safe_title}.srt")
            vid_out = os.path.join(install_dir, "lf_output", f"Final_LF_{safe_title}.mp4")
            
            # 1. Script Generation Checkpoint
            print("[+] Beginning Script Generation")

            target_min = int(settings.get("lf_target_minutes", 2))

            groq_keys = settings.get("groq_api_keys", [])
            if not groq_keys:
                for p_name, p_data in self.master_settings.items():
                    alt = p_data.get("groq_api_keys", [])
                    if alt:
                        groq_keys = alt
                        break

            from script_generator import LongFormScripter
            scripter = LongFormScripter(
                groq_keys,
                target_minutes=target_min
            )

            manual_mode = settings.get("lf_manual_script_enabled", False) or is_manual_job
            manual_path = getattr(self, "manual_script_path", "").strip()

            # --- DURATION-AWARE CACHE CHECK ---
            # If the user changed target duration, purge mismatched cached scripts/audios automatically
            if not manual_mode and os.path.exists(script_file):
                try:
                    with open(script_file, "r", encoding="utf-8") as sf:
                        cached_words = len(sf.read().split())
                    expected_words = target_min * 140
                    # If cached script deviates significantly from target duration, invalidate cache
                    if abs(cached_words - expected_words) > max(150, expected_words * 0.5):
                        print(f"   > 🔄 Target Duration Mismatch: Cached script ({cached_words} words) != Target ({target_min} min / ~{expected_words} words).")
                        print(f"   > 🧹 Auto-purging outdated cache files for fresh {target_min}-minute generation...")
                        for cf in [script_file, audio_out, srt_out, vid_out]:
                            if os.path.exists(cf):
                                try: os.remove(cf)
                                except Exception: pass
                except Exception:
                    pass

            if is_manual_job:
                # Always ensure fresh audio and subtitles for manual script renders
                for old_f in [audio_out, srt_out]:
                    if os.path.exists(old_f):
                        try: os.remove(old_f)
                        except Exception: pass

            if manual_mode:
                if manual_path and os.path.exists(manual_path):
                    try:
                        with open(manual_path, "r", encoding="utf-8", errors="ignore") as mf:
                            m_content = mf.read().strip()
                    except Exception:
                        m_content = ""
                    if not m_content:
                        print(f"   > ❌ Manual Script Error: '{manual_path}' is empty (0 words/bytes).")
                        print("   > 📌 Please open the file on your Desktop and add script text before rendering.")
                        self.after(0, lambda: messagebox.showwarning("Empty Script", "The manual script file is empty! Please write or paste your script before rendering."))
                        return

                    target_lang = settings.get("lf_main_language", "Russian")
                    has_cyrillic = bool(re.search(r'[\u0400-\u04FF]', m_content))
                    has_latin = bool(re.search(r'[a-zA-Z]', m_content))

                    # If user chose Russian profile but script is English, auto-translate via Groq!
                    if target_lang.lower() in ["russian", "ru"] and not has_cyrillic and has_latin:
                        print(f"   > 🌐 Language Alignment: Script is in English, but Profile Language is set to Russian.")
                        print(f"   > 🤖 Translating narrative to Russian via Groq AI so voiceover speaks authentic Russian...")
                        translated_text = scripter.translate_script_to_language(m_content, target_language="Russian")
                        if translated_text and re.search(r'[\u0400-\u04FF]', translated_text):
                            m_content = translated_text
                            print(f"   > ✅ Script successfully translated to Russian ({len(m_content.split())} words)!")
                    elif target_lang.lower() in ["english", "en"] and has_cyrillic and not has_latin:
                        print(f"   > 🌐 Language Alignment: Script is in Russian, but Profile Language is set to English.")
                        print(f"   > 🤖 Translating narrative to English via Groq AI...")
                        translated_text = scripter.translate_script_to_language(m_content, target_language="English")
                        if translated_text:
                            m_content = translated_text
                            print(f"   > ✅ Script successfully translated to English ({len(m_content.split())} words)!")

                    os.makedirs(os.path.dirname(script_file) if os.path.dirname(script_file) else "lf_scripts", exist_ok=True)
                    with open(script_file, "w", encoding="utf-8") as sf:
                        sf.write(m_content)
                    print(f"   > 📄 Manual Script Mode ACTIVE: Saved to '{script_file}'")
                    print("   > ⚡ Groq script generation SKIPPED.")
                    print("[+] Script Ready")
                else:
                    print("   > ❌ Manual Script Mode is ON but no valid .txt file is selected.")
                    print("   > 📌 Please use the Browse button on the main dashboard to select a script.")
                    return
            else:
                # Normal Groq generation path

                if os.path.exists(script_file):
                    print(f"   > 📂 Smart Resume: Found existing script file: {script_file}. Bypassing generation.")
                    print("[+] Groq Script Created")
                else:
                    script_file = scripter.generate_full_script(
                        title=title,
                        language=settings.get("lf_main_language", "English"),
                        style=settings.get("lf_script_style", "Deep Emotional")
                    )
                    if script_file and os.path.exists(script_file):
                        print("[+] Groq Script Created")

                if not script_file or not os.path.exists(script_file):
                    print("   > ❌ Script file missing or failed. Will retry next cycle.")
                    return

            # Read script content to generate dynamic AI metadata
            metadata_language = settings.get("lf_metadata_language", "English")
            with open(script_file, "r", encoding="utf-8") as f:
                script_text = f.read()

            metadata = scripter.generate_youtube_metadata(script_text, language=metadata_language)
            if metadata and metadata.get("title") and metadata.get("description"):
                ai_title = metadata["title"]
                ai_description = metadata["description"]
                ai_tags = metadata.get("tags", [])
                print(f"   > 🤖 Dynamic AI Metadata Generated:")
                print(f"     - Title: {ai_title}")
                print(f"     - Tags: {ai_tags}")
            else:
                ai_title = title
                ai_description = f"✨ {title}\n\nDon't forget to Like and Subscribe!"
                ai_tags = []
                print(f"   > ⚠️ Falling back to original queue metadata.")

            # 2. Audio Generation Checkpoint
            print("[+] Beginning Chunked Audio Generation")
            if os.path.exists(audio_out) and os.path.getsize(audio_out) > 0:
                print(f"   > 📂 Smart Resume: Found existing audio file: {audio_out}. Bypassing generation.")
                print("[+] Chunked Audio Generation Complete")
            else:
                voice_actor = settings.get("lf_voice_actor", "US Male Deep")
                asyncio.run(long_form_composer.generate_tts(
                    script_file, 
                    settings.get("lf_main_language", "English"), 
                    audio_out,
                    voice_actor=voice_actor,
                    progress_callback=self.update_task_progress
                ))
                if os.path.exists(audio_out) and os.path.getsize(audio_out) > 0:
                    print("[+] Chunked Audio Generation Complete")
                else:
                    print(f"   > ❌ Audio Generation Failed: Audio file '{audio_out}' was not created.")
                    print("   > 📌 Aborting video rendering to prevent FFmpeg crash.")
                    return

            # 3. Subtitle Generation Checkpoint
            hw_mode = settings.get("lf_hardware_mode", "Standard")
            enable_subs = settings.get("lf_subtitles_enabled", True)
            hw_profile = settings.get("hardware_profile", "cpu")
            
            if enable_subs:
                if os.path.exists(srt_out):
                    print(f"   > 📂 Smart Resume: Found existing subtitle file: {srt_out}. Bypassing generation.")
                else:
                    self.update_task_progress(50, "Transcribing Subtitles (Groq)")
                    long_form_composer.generate_srt(
                        audio_out, 
                        srt_out, 
                        hardware_mode=hw_mode,
                        device=hw_profile,
                        language=settings.get("lf_main_language", "English"),
                        groq_api_keys=groq_keys
                    )
                    self.update_task_progress(100, "Subtitles Ready")
            else:
                print("   > 🚫 Subtitles are disabled. Skipping subtitle generation.")
                srt_out = None
            
            # Resolve background video and music dynamically
            use_custom_image_bg = False
            if is_manual_job and manual_thumb and os.path.exists(manual_thumb):
                bg_video = None
                image_path = manual_thumb
                use_custom_image_bg = True
                print(f"   > 🖼️ Custom Picture ACTIVE: Using selected image as video background: '{os.path.basename(manual_thumb)}'")
            elif not is_manual_job and image_path and os.path.exists(image_path):
                # Discord queue job with attached picture: Use the attached picture as the video background!
                bg_video = None
                use_custom_image_bg = True
                print(f"   > 🖼️ Discord Picture ACTIVE: Using attached image as video background: '{os.path.basename(image_path)}'")
            else:
                bg_video = long_form_composer.get_next_background_video()
                if bg_video:
                    print(f"   > 🎥 Background Video ACTIVE: Using '{os.path.basename(bg_video)}' from 'bg' folder.")
                else:
                    print(f"   > 🖼️ Still Image ACTIVE: Using '{os.path.basename(image_path)}' as video background.")

            bg_music = settings.get("lf_bg_music", "")
            if not bg_music or not os.path.exists(bg_music):
                bg_music = long_form_composer.get_next_background_music()

            # Retrieve styling configurations and switches
            bg_music_enabled = settings.get("lf_bg_music_enabled", True)
            sub_color = settings.get("lf_sub_color", "Yellow")
            sub_position = settings.get("lf_sub_position", "Bottom")
            sub_size = settings.get("lf_sub_size", "24")

            # 4. Video Rendering
            print("[+] Beginning Video Composition")
            self.update_task_progress(0, "Rendering Video (0%)")
            success = long_form_composer.render_long_form_video(
                image_path=image_path, 
                audio_path=audio_out, 
                srt_path=srt_out, 
                bg_music_path=bg_music, 
                final_output_path=vid_out,
                sub_size=sub_size,
                sub_color=sub_color,
                sub_position=sub_position,
                hardware_mode=hw_mode,
                device=hw_profile,
                bg_music_enabled=bg_music_enabled,
                progress_callback=self.update_task_progress,
                bg_video_path=bg_video,
                use_image_bg=use_custom_image_bg
            )
            
            if success:
                print("[+] Video Composition Complete")
                
                print("[+] Beginning YouTube Upload")
                profile_yt_token = os.path.join(install_dir, "credentials", prof_name, "token.json")
                social_engine.upload_to_youtube(
                    vid_out, ai_title, ai_description, profile_yt_token,
                    thumbnail_path=image_path,
                    progress_callback=self.update_upload_progress,
                    tags=ai_tags,
                    language=settings.get("lf_main_language", "English")
                )
                print("[+] YouTube Upload Success")
                
                # Part 2: Persistent Time Tracking & Cloud Sync
                import time
                current_time = time.time()
                self.set_active_setting("lf_last_upload_time", current_time)
                self.save_settings()
                
                try:
                    timestamp_str = datetime.fromtimestamp(current_time).isoformat()
                    personal_url = settings.get("personal_sheet_url", "")
                    if personal_url:
                        cloud_logger.sync_lf_timestamp(personal_url, timestamp_str)
                except Exception as sync_e:
                    print(f"   > ⚠️ Failed to sync Long-Form timestamp to cloud: {sync_e}")
                
                # Append title to published history on success (for automated YouTube posts only)
                if not is_manual_job:
                    try:
                        with open(history_file, "a", encoding="utf-8") as f:
                            f.write(title + "\n")
                        print("   > 📝 Appended title to published history ledger.")
                    except Exception as e:
                        print(f"   > ⚠️ Warning: Failed to write to published history ledger: {e}")

                if not is_manual_job:
                    # Remove the completed item from the queue
                    queue_data.pop(0)
                    with open(queue_file, "w") as f:
                        json.dump(queue_data, f, indent=4)
                else:
                    # Clear manual script & thumbnail so it doesn't re-run in loop
                    self.manual_script_path = ""
                    self.set_active_setting("lf_manual_script_path", "")
                    self.manual_thumbnail_path = ""
                    self.set_active_setting("lf_manual_thumbnail_path", "")
                    self.save_settings()
                    def _clear_ui():
                        try:
                            self.manual_script_entry.delete(0, "end")
                            if hasattr(self, "manual_thumb_entry"):
                                self.manual_thumb_entry.delete(0, "end")
                        except Exception:
                            pass
                    self.after(0, _clear_ui)
                    print(f"   > 📄 Manual script job completed successfully.")
                    
                if not is_manual_job:
                    # Reset the local timer only for automated queue jobs
                    with open(lf_log_file, "w") as f:
                        f.write(datetime.now().isoformat())
                    
                print("========================================")
                print(f"✅ CYCLE COMPLETE: [{prof_name}] - {title}")
                print("========================================")

                if is_manual_job:
                    manual_record = {
                        "timestamp": datetime.now().isoformat(),
                        "profile": prof_name,
                        "title": title,
                        "script_path": manual_path,
                        "thumbnail_path": chosen_img,
                        "audio_out": audio_out,
                        "subtitles_out": srt_out,
                        "video_out": vid_out,
                        "language": settings.get("lf_main_language", "Russian"),
                        "voice_actor": settings.get("lf_voice_actor", "Xenia (Default Female)"),
                        "status": "SUCCESS"
                    }
                    try:
                        rec_file = os.path.join(install_dir, "lf_manual_renders.json")
                        history_records = []
                        if os.path.exists(rec_file):
                            with open(rec_file, "r", encoding="utf-8") as rf:
                                history_records = json.load(rf)
                        history_records.append(manual_record)
                        with open(rec_file, "w", encoding="utf-8") as rf:
                            json.dump(history_records, rf, indent=4)
                        with open(os.path.join(install_dir, "lf_manual_renders.log"), "a", encoding="utf-8") as ml:
                            ml.write(f"[{manual_record['timestamp']}] SUCCESS | Script: {os.path.basename(manual_path)} | Thumbnail: {os.path.basename(chosen_img)} | Video: {vid_out}\n")
                        print("   > 📝 Manual Render recorded to lf_manual_renders.json and lf_manual_renders.log.")
                    except Exception as he:
                        print(f"   > ⚠️ Warning recording manual render: {he}")
                    print("   > 💾 Manual Script Job: Preserved all script, audio, subtitle, and video files permanently.")
                else:
                    # Part 3: Delayed Cleanup for automated jobs only (never delete final video!)
                    import threading
                    files_to_wipe = [script_file, audio_out, srt_out]
                    threading.Thread(target=self.delayed_asset_cleanup, args=(files_to_wipe,), daemon=True).start()
                    print("   > 🧹 Automated Queue: Temp audio/subtitle cleanup scheduled in 10 minutes.")
                return True
        except Exception as e:
            import traceback
            print(f"   > ❌ Long-Form Pipeline Error: {e}")
            print(traceback.format_exc())
            return False
        finally:
            self.engine_is_busy = False

    def trigger_manual_long_form(self):
        if self.engine_is_busy:
            print("   > ⚠️ Engine is currently busy rendering. Please wait for the current render to complete.")
            messagebox.showwarning("Engine Busy", "The engine is currently busy rendering another video.\nPlease wait for it to complete.")
            return

        print(f"\n========================================")
        print(f"⚡ MANUAL OVERRIDE: Forcing Immediate Long-Form Generation for Pending Queue (Ignoring Interval)...")
        print(f"========================================")

        import threading
        threading.Thread(
            target=self._run_force_queue_worker,
            daemon=True
        ).start()

    def _run_force_queue_worker(self):
        total_processed = 0
        while True:
            # Find next pending queue item across active profile first, then any other profile
            target_prof = self.active_profile
            target_settings = self.master_settings.get(target_prof, {})
            target_queue_file = os.path.join(install_dir, "lf_queues", f"queue_{target_prof.replace(' ', '_')}.json")
            
            has_item = False
            if os.path.exists(target_queue_file):
                try:
                    with open(target_queue_file, "r") as f:
                        q = json.load(f)
                        if q and len(q) > 0:
                            has_item = True
                except Exception:
                    pass
                    
            if not has_item:
                # Check other profiles in case items were submitted to another profile
                for other_p, other_s in self.master_settings.items():
                    if other_p == target_prof:
                        continue
                    oq_file = os.path.join(install_dir, "lf_queues", f"queue_{other_p.replace(' ', '_')}.json")
                    if os.path.exists(oq_file):
                        try:
                            with open(oq_file, "r") as f:
                                q = json.load(f)
                                if q and len(q) > 0:
                                    target_prof = other_p
                                    target_settings = other_s
                                    has_item = True
                                    break
                        except Exception:
                            pass
            
            if not has_item:
                if total_processed == 0:
                    # Check if there's a manual script as fallback
                    manual_path = getattr(self, "manual_script_path", "").strip() or target_settings.get("lf_manual_script_path", "").strip()
                    if manual_path and os.path.exists(manual_path):
                        print(f"   > ℹ️ [Force Queue] No items pending in queue. Running selected manual script: {os.path.basename(manual_path)}")
                        self.process_long_form_queue(target_prof, target_settings, force=True, is_manual_script=True)
                        break
                    else:
                        print(f"   > ⚠️ [Force Queue] No pending items in queue for [{self.active_profile}] or any other profile.")
                        self.after(0, lambda: messagebox.showinfo("Queue Empty", "The queue is currently empty.\n\nSend a title + image to your Discord channel to add items to the queue, or select a manual script above."))
                else:
                    print(f"\n   > 🎉 [Force Queue] Completed all pending jobs ({total_processed} total). Queue is now clear!")
                    self.after(0, lambda: messagebox.showinfo("Queue Complete", f"All pending queue items have been generated and processed successfully!\n({total_processed} video(s) rendered)"))
                break
                
            print(f"\n⚡ [Force Queue] Processing pending job #{total_processed + 1} for [{target_prof}] (Time interval IGNORED)...")
            success = self.process_long_form_queue(target_prof, target_settings, force=True, force_queue=True)
            if success:
                total_processed += 1
                time.sleep(2)
            else:
                print(f"   > ⚠️ [Force Queue] Processing stopped after {total_processed} item(s).")
                break

    def trigger_manual_last_render_upload(self):
        output_dir = os.path.join(install_dir, "lf_output")
        if not os.path.exists(output_dir):
            messagebox.showerror("Error", "Output folder not found.")
            return
            
        mp4_files = glob.glob(os.path.join(output_dir, "*.mp4"))
        if not mp4_files:
            messagebox.showerror("Error", "No rendered videos (.mp4) found in the output folder.")
            return
            
        # Get most recently modified file
        latest_video = max(mp4_files, key=os.path.getmtime)
        video_name = os.path.basename(latest_video)
        
        title_suggestion = os.path.splitext(video_name)[0].replace("Final_LF_", "").replace("_", " ")
        
        if not messagebox.askyesno("Confirm Upload", f"Are you sure you want to upload the most recent render?\n\nFile: {video_name}\nSuggested Title: {title_suggestion}"):
            return
            
        title = simpledialog.askstring("Video Title", "Enter YouTube Title:", initialvalue=title_suggestion)
        if not title:
            return
            
        description = simpledialog.askstring("Video Description", "Enter YouTube Description:", initialvalue=f"✨ {title}\n\nDon't forget to Like and Subscribe!\n\n#Documentary #LongForm #IslamicHistory")
        if not description:
            return
            
        thumbnail_path = None
        if messagebox.askyesno("Custom Thumbnail", "Would you like to select a custom thumbnail image?"):
            thumbnail_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.jpg *.png *.jpeg")])
            if not thumbnail_path:
                thumbnail_path = None
                 
        prof_name = self.active_profile
        profile_yt_token = os.path.join(install_dir, "credentials", prof_name, "token.json")
        
        print(f"[+] Beginning YouTube Upload for manual render: {video_name}")
        
        def upload_thread():
            try:
                social_engine.upload_to_youtube(
                    latest_video, 
                    title, 
                    description, 
                    profile_yt_token, 
                    thumbnail_path=thumbnail_path,
                    progress_callback=self.update_upload_progress,
                    language=settings.get("lf_main_language", "English")
                )
                print("[+] YouTube Upload Success")
            except Exception as e:
                print(f"[x] Error during manual upload: {e}")
                 
        threading.Thread(target=upload_thread, daemon=True).start()

    def delayed_asset_cleanup(self, files_to_delete):
        import time
        import os
        print(f"   > 🕒 Asset Cleanup thread started. Sleeping for 10 minutes...")
        time.sleep(600)
        print(f"   > 🧹 Asset Cleanup: Starting removal of temporary files...")
        for filepath in files_to_delete:
            if filepath:
                # Safeguard: Never delete rendered mp4 videos or output files
                if filepath.lower().endswith(".mp4") or "lf_output" in filepath:
                    continue
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        print(f"   > 🗑️ Deleted temp file: {os.path.basename(filepath)}")
                except Exception as e:
                    pass
        print(f"   > 🧹 Asset Cleanup complete.")

    def run_pipeline(self):
        print("[SYSTEM] Long-Form Automation Engine started. Scanning profile queues...")
        while self.is_running:
            try:
                profiles_snapshot = list(self.master_settings.items())
                for prof_name, settings in profiles_snapshot:
                    if not self.is_running: break
                    # Only process profiles that have lf_enabled=True
                    if not settings.get("lf_enabled", True):
                        print(f"   > ⏭️ Skipping [{prof_name}]: lf_enabled is OFF")
                        continue
                    print(f"   > 🔍 Scanning queue for [{prof_name}]...")
                    self.process_long_form_queue(prof_name, dict(settings))
                    
                # Poll every 30 seconds with 1-second ticks
                print("   > ⏰ Scan complete. Waiting 30 seconds before next scan...")
                for _ in range(30):
                    if not self.is_running: break
                    time.sleep(1)
                    
            except Exception as e:
                import traceback
                print(f"\n❌ CRITICAL GLOBAL ERROR IN PIPELINE LOOP:\n{traceback.format_exc()}")
                time.sleep(5)
        
        def reset_btn():
            self.engine_thread_active = False 
            self.generate_btn.configure(text="🎬 START LONG-FORM AUTOMATION ENGINE", fg_color=["#2CC985", "#2FA572"], hover_color=["#209661", "#22855A"])
        self.after(0, reset_btn)

if __name__ == "__main__":
    multiprocessing.freeze_support() 
    try:
        app = IslamicReelsStudio()
        app.mainloop()
    except Exception as e:
        import traceback
        print("\n[SYSTEM CRASHED BEFORE UI COULD LOAD]")
        print("---------------------------------------")
        print(traceback.format_exc())
        input("\nPress Enter to exit...")
