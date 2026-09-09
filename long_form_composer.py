import sys

# --- GLOBAL ENCODING FIX ---
# Force Windows terminal to support UTF-8 emojis without crashing
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
# ---------------------------

import os

# --- GLOBAL FFMPEG PATH INJECTION ---
# Failsafe: prepend C:\ffmpeg\bin to PATH so ALL subprocesses (including pydub's
# internal mediainfo_json) can locate ffmpeg.exe and ffprobe.exe natively.
_ffmpeg_bin_path = r"C:\ffmpeg\bin"
if _ffmpeg_bin_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_bin_path + os.pathsep + os.environ.get("PATH", "")
# ------------------------------------

FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\ffmpeg\bin\ffprobe.exe"

# Set environment variable to force libraries like imageio_ffmpeg / moviepy to use this binary
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_PATH

# Fallback safety check to alert the developer immediately if the drive path is wrong
if not os.path.exists(FFMPEG_PATH):
    print(f"[CRITICAL] FFmpeg binary not found at {FFMPEG_PATH}. Video rendering will fail.")

import asyncio
import subprocess
import imageio_ffmpeg
import math
import psutil
import time
import collections
import threading
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Module-level helpers: dynamic RAM allocation + nvidia-smi GPU detection
# ---------------------------------------------------------------------------

def _get_ram_allocation():
    """Returns (total_gb, allocated_gb, allocated_bytes) using 75% of total RAM."""
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    allocated_gb = total_gb * 0.75
    allocated_bytes = int(mem.total * 0.75)
    return round(total_gb, 1), round(allocated_gb, 1), allocated_bytes

_cuda_dlls_registered = False
def setup_cuda_dll_paths():
    """Locates and registers NVIDIA CUDA/cuBLAS/cuDNN DLL directories with Windows OS."""
    global _cuda_dlls_registered
    if _cuda_dlls_registered or sys.platform != "win32":
        return
    try:
        import site
        search_dirs = []
        if hasattr(site, 'getsitepackages'):
            for sp in site.getsitepackages():
                if os.path.isdir(sp): search_dirs.append(sp)
        if hasattr(site, 'getusersitepackages'):
            usp = site.getusersitepackages()
            if os.path.isdir(usp): search_dirs.append(usp)
        
        base_dir = os.path.dirname(os.path.dirname(sys.executable))
        venv_sp = os.path.join(base_dir, "Lib", "site-packages")
        if os.path.isdir(venv_sp) and venv_sp not in search_dirs:
            search_dirs.append(venv_sp)
            
        for sp in search_dirs:
            nvidia_root = os.path.join(sp, "nvidia")
            if os.path.isdir(nvidia_root):
                for root, dirs, files in os.walk(nvidia_root):
                    if any(f.lower().endswith(".dll") for f in files):
                        try:
                            os.add_dll_directory(root)
                        except Exception:
                            pass
                        if root not in os.environ.get("PATH", ""):
                            os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
        _cuda_dlls_registered = True
    except Exception:
        pass

def is_cublas_available():
    """Checks if NVIDIA cuBLAS libraries are installed and loadable for CTranslate2 / Whisper."""
    setup_cuda_dll_paths()
    import ctypes
    for dll in ["cublas64_12.dll", "cublas64_11.dll"]:
        try:
            ctypes.CDLL(dll)
            return True
        except Exception:
            pass
    return False

def get_nvidia_gpu_info():
    """Returns (has_nvidia: bool, gpu_name: str, vram_gb: float) for NVIDIA GPU (e.g. GTX 1660 Super 6GB)."""
    # 1. nvidia-smi (Fastest & direct via NVIDIA display driver)
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
            name = parts[0]
            mb = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '', 1).isdigit() else 6144.0
            return True, name, round(mb / 1024, 1)
    except Exception:
        pass

    # 2. PyTorch CUDA
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            try:
                vram_bytes = torch.cuda.get_device_properties(0).total_memory
                vram_gb = round(vram_bytes / (1024 ** 3), 1)
            except Exception:
                vram_gb = 6.0
            return True, name, vram_gb
    except Exception:
        pass

    # 3. Windows CimInstance
    try:
        cmd = 'powershell -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        for l in out.splitlines():
            line_str = l.strip()
            if any(k in line_str.lower() for k in ["nvidia", "geforce", "gtx", "rtx"]):
                vram_gb = 6.0 if "1660" in line_str else 4.0
                return True, line_str, vram_gb
    except Exception:
        pass

    return False, "", 0.0

def detect_nvidia_gpu():
    """Returns True if NVIDIA GPU is detected, logging model name and VRAM."""
    has_gpu, name, vram = get_nvidia_gpu_info()
    if has_gpu:
        print(f"[+] 🎮 NVIDIA GPU Active: {name} | VRAM: {vram} GB | Hardware Acceleration: NVENC + CUDA", flush=True)
        return True
    print("[-] No discrete GPU Detected: Falling back to CPU rendering (libx264)", flush=True)
    return False
# ---------------------------------------------------------------------------

# PATH injection above supersedes explicit AudioSegment attribute overrides.
# Pydub will now resolve ffmpeg/ffprobe via the system PATH set above.
from pydub import AudioSegment

TEMP_DIR = os.path.join(os.getcwd(), "lf_temp")
OUTPUT_DIR = os.path.join(os.getcwd(), "lf_output")
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

from audio_generator import generate_tts, VOICE_ACTORS, TTS_VOICES, LANG_CODES

def format_time(seconds):
    """Formats seconds into SRT time format (00:00:00,000)"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msec = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msec:03d}"

def generate_srt_groq(audio_path, srt_output_path, language="English", groq_api_keys=None):
    """
    Transcribes audio using ultra-fast Groq Cloud LPU Whisper AI (whisper-large-v3-turbo).
    Processes entire audio in ~10-15 seconds with zero local CPU load.
    """
    from groq import Groq
    import time
    
    # Parse API keys
    if isinstance(groq_api_keys, str):
        keys = [k.strip() for k in groq_api_keys.split(",") if k.strip()]
    elif isinstance(groq_api_keys, list):
        keys = [k.strip() for k in groq_api_keys if k.strip()]
    else:
        keys = []
        
    if not keys:
        return False
        
    whisper_lang = LANG_CODES.get(language, "en")
    print(f"\n   > ⚡ [Groq LPU Whisper] Preparing cloud audio transcription (Language: '{whisper_lang}')...")
    
    # Convert audio to lightweight 64k mono MP3 for fast upload payload (<10MB even for 1hr)
    temp_upload_audio = os.path.join(TEMP_DIR, "temp_groq_whisper.mp3")
    try:
        ffmpeg_bin = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", audio_path,
            "-ac", "1",
            "-b:a", "64k",
            temp_upload_audio
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        file_to_send = temp_upload_audio
    except Exception:
        file_to_send = audio_path
        
    start_time = time.time()
    file_size_mb = os.path.getsize(file_to_send) / (1024 * 1024) if os.path.exists(file_to_send) else 0
    
    # If audio is larger than 22MB (e.g. multi-hour video), segment into 10-min parts for Groq 25MB limit
    if file_size_mb > 22.0:
        print(f"   > 📦 Audio payload ({file_size_mb:.1f}MB) exceeds 22MB. Segmenting into 10-minute parts for Groq Cloud...")
        segment_pattern = os.path.join(TEMP_DIR, "temp_whisper_seg_%03d.mp3")
        ffmpeg_bin = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"
        seg_cmd = [
            ffmpeg_bin, "-y",
            "-i", file_to_send,
            "-f", "segment", "-segment_time", "600",
            "-c", "copy",
            segment_pattern
        ]
        subprocess.run(seg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        import glob
        seg_files = sorted(glob.glob(os.path.join(TEMP_DIR, "temp_whisper_seg_*.mp3")))
    else:
        seg_files = [file_to_send]

    for key_idx, key in enumerate(keys):
        try:
            print(f"   > 🚀 Transcribing via Groq Cloud Whisper API (Key #{key_idx + 1} | Parts: {len(seg_files)})...")
            client = Groq(api_key=key)
            all_segments = []
            
            for seg_idx, sf_path in enumerate(seg_files):
                time_offset = seg_idx * 600.0
                with open(sf_path, "rb") as af:
                    transcription = client.audio.transcriptions.create(
                        file=af,
                        model="whisper-large-v3-turbo",
                        response_format="verbose_json",
                        language=whisper_lang,
                        temperature=0.0
                    )
                part_segs = getattr(transcription, "segments", [])
                if not part_segs and isinstance(transcription, dict):
                    part_segs = transcription.get("segments", [])
                for s in part_segs:
                    s["time_offset"] = time_offset
                    all_segments.append(s)

            if os.path.exists(srt_output_path):
                try: os.remove(srt_output_path)
                except Exception: pass
                
            subtitle_index = 1
            with open(srt_output_path, "w", encoding="utf-8") as f:
                for segment in all_segments:
                    offset = segment.get("time_offset", 0.0)
                    words = segment.get("words", []) if isinstance(segment, dict) else getattr(segment, "words", [])
                    if words:
                        for idx in range(0, len(words), 8):
                            w_chunk = words[idx : idx + 8]
                            c_text = " ".join((w["word"] if isinstance(w, dict) else w.word).strip() for w in w_chunk)
                            s_start = (w_chunk[0]["start"] if isinstance(w_chunk[0], dict) else w_chunk[0].start) + offset
                            s_end = (w_chunk[-1]["end"] if isinstance(w_chunk[-1], dict) else w_chunk[-1].end) + offset
                            f.write(f"{subtitle_index}\n{format_time(s_start)} --> {format_time(s_end)}\n{c_text}\n\n")
                            subtitle_index += 1
                    else:
                        s_start = (segment["start"] if isinstance(segment, dict) else segment.start) + offset
                        s_end = (segment["end"] if isinstance(segment, dict) else segment.end) + offset
                        s_text = (segment["text"] if isinstance(segment, dict) else segment.text).strip()
                        s_words = s_text.split()
                        if len(s_words) > 8:
                            duration = s_end - s_start
                            num_chunks = math.ceil(len(s_words) / 8)
                            chunk_dur = duration / num_chunks
                            for chunk_idx in range(num_chunks):
                                sub_w = s_words[chunk_idx * 8 : (chunk_idx + 1) * 8]
                                chunk_text = " ".join(sub_w)
                                c_start = s_start + (chunk_idx * chunk_dur)
                                c_end = c_start + chunk_dur
                                f.write(f"{subtitle_index}\n{format_time(c_start)} --> {format_time(c_end)}\n{chunk_text}\n\n")
                                subtitle_index += 1
                        else:
                            f.write(f"{subtitle_index}\n{format_time(s_start)} --> {format_time(s_end)}\n{s_text}\n\n")
                            subtitle_index += 1

            elapsed = time.time() - start_time
            print(f"   > ✅ [Groq LPU Whisper] Subtitles generated successfully in {elapsed:.1f} seconds! (Saved: {srt_output_path})")
            if os.path.exists(temp_upload_audio):
                try: os.remove(temp_upload_audio)
                except Exception: pass
            for sf_p in seg_files:
                if sf_p != file_to_send and os.path.exists(sf_p):
                    try: os.remove(sf_p)
                    except Exception: pass
            return True
        except Exception as e:
            print(f"   > ⚠️ Groq Cloud Whisper error on Key #{key_idx + 1}: {e}")
            
    if os.path.exists(temp_upload_audio):
        try: os.remove(temp_upload_audio)
        except Exception: pass
    return False

def generate_srt(audio_path, srt_output_path, hardware_mode="Standard", device="cpu", language="English", groq_api_keys=None):
    # 1. Try Ultra-Fast Groq Cloud LPU Whisper first (~10-15 seconds)
    if groq_api_keys:
        groq_success = generate_srt_groq(audio_path, srt_output_path, language=language, groq_api_keys=groq_api_keys)
        if groq_success and os.path.exists(srt_output_path):
            return True
            
    # 2. Fallback to Local CPU/GPU Whisper if Groq keys are absent or fail
    print("   > 🧠 Running Local Whisper AI to generate .srt Subtitles (Fallback mode)...")
    
    total_gb, allocated_gb, _ = _get_ram_allocation()
    logical_cores = psutil.cpu_count(logical=True) or 4
    if hardware_mode == "Low-End PC (Fastest)":
        cpu_threads = max(2, logical_cores // 4)
    elif hardware_mode == "High-End Workstation":
        cpu_threads = min(logical_cores, 16)
    else:
        cpu_threads = max(2, logical_cores // 2)
        
    print(f"   > ⚙️ Whisper Threads Allocated: {cpu_threads} | RAM Budget: {allocated_gb}GB / {total_gb}GB (75%)") 
    
    has_nvidia, gpu_name, vram_gb = get_nvidia_gpu_info()
    use_cuda = (device == "cuda")
    if use_cuda:
        if not is_cublas_available():
            print(f"   > ℹ️ CUDA Whisper Notice: cuBLAS library (cublas64_12.dll) not found on system. Switching to multi-threaded CPU Whisper...", flush=True)
            use_cuda = False

    whisper_device = "cuda" if use_cuda else "cpu"
    
    model = None
    if whisper_device == "cuda":
        try:
            print(f"   > 🚀 Initializing Whisper AI on NVIDIA GPU ({gpu_name or 'GTX 1660 Super 6GB'} | CUDA FP16)...", flush=True)
            model = WhisperModel("base", device="cuda", compute_type="float16")
            print("   > ✅ Whisper AI GPU Engine loaded successfully on CUDA!", flush=True)
        except Exception as e:
            print(f"   > ℹ️ CUDA Whisper runtime notice ({e}). Running multi-threaded CPU Whisper...", flush=True)
            model = None

    if model is None:
        model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=cpu_threads)
        print(f"   > ⚙️ Whisper running on CPU multi-threaded engine ({cpu_threads} threads).", flush=True)
    
    audio = AudioSegment.from_file(audio_path)
    chunk_length_ms = 60 * 1000
    total_chunks = math.ceil(len(audio) / chunk_length_ms)
    
    if os.path.exists(srt_output_path):
        try: os.remove(srt_output_path)
        except: pass
            
    subtitle_index = 1
    temp_chunk_path = "lf_temp/temp_whisper_chunk.wav"
    whisper_lang = LANG_CODES.get(language, "en")
    
    with open(srt_output_path, "a", encoding="utf-8") as f:
        for i in range(total_chunks):
            print(f"   > 🧠 Transcribing chunk {i+1}/{total_chunks} in language: '{whisper_lang}'...")
            chunk = audio[i * chunk_length_ms : (i + 1) * chunk_length_ms]
            chunk.export(temp_chunk_path, format="wav")
            
            segment_list = []
            try:
                segments, _ = model.transcribe(temp_chunk_path, vad_filter=True, language=whisper_lang, word_timestamps=True)
                segment_list = list(segments)
            except Exception as e:
                print(f"   > ⚠️ Whisper GPU transcription failed ({e}).", flush=True)
                print(f"   > 🔄 Auto Hardware Fallback: Switching Whisper to multi-threaded CPU engine ({cpu_threads} threads)...", flush=True)
                try:
                    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=cpu_threads)
                    segments, _ = model.transcribe(temp_chunk_path, vad_filter=True, language=whisper_lang, word_timestamps=True)
                    segment_list = list(segments)
                except Exception as e2:
                    print(f"   > ❌ Whisper CPU transcription error on chunk {i+1}: {e2}", flush=True)
                    segment_list = []

            time_offset = i * 60.0
            
            for segment in segment_list:
                segment_words = list(segment.words) if segment.words else []
                if segment_words:
                    for idx in range(0, len(segment_words), 8):
                        word_chunk = segment_words[idx : idx + 8]
                        chunk_text = " ".join(w.word.strip() for w in word_chunk)
                        
                        adjusted_start = word_chunk[0].start + time_offset
                        adjusted_end = word_chunk[-1].end + time_offset
                        
                        start_time = format_time(adjusted_start)
                        end_time = format_time(adjusted_end)
                        
                        f.write(f"{subtitle_index}\n{start_time} --> {end_time}\n{chunk_text}\n\n")
                        subtitle_index += 1
                else:
                    adjusted_start = segment.start + time_offset
                    adjusted_end = segment.end + time_offset
                    text = segment.text.strip()
                    words = text.split()
                    
                    if len(words) > 8:
                        duration = adjusted_end - adjusted_start
                        num_chunks = math.ceil(len(words) / 8)
                        chunk_duration = duration / num_chunks
                        for chunk_idx in range(num_chunks):
                            sub_words = words[chunk_idx * 8 : (chunk_idx + 1) * 8]
                            chunk_text = " ".join(sub_words)
                            c_start = adjusted_start + (chunk_idx * chunk_duration)
                            c_end = c_start + chunk_duration
                            
                            start_time = format_time(c_start)
                            end_time = format_time(c_end)
                            f.write(f"{subtitle_index}\n{start_time} --> {end_time}\n{chunk_text}\n\n")
                            subtitle_index += 1
                    else:
                        start_time = format_time(adjusted_start)
                        end_time = format_time(adjusted_end)
                        f.write(f"{subtitle_index}\n{start_time} --> {end_time}\n{text}\n\n")
                        subtitle_index += 1
                
    if os.path.exists(temp_chunk_path):
        try: os.remove(temp_chunk_path)
        except Exception: pass
    return True
            
    print(f"   > ✅ Subtitle file generated: {srt_output_path}")

_nvenc_tested = None
def is_nvenc_functional():
    global _nvenc_tested
    if _nvenc_tested is not None:
        return _nvenc_tested
    try:
        ffmpeg_bin = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"
        test_cmd = [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"]
        res = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5)
        _nvenc_tested = (res.returncode == 0)
    except Exception:
        _nvenc_tested = False
    return _nvenc_tested

def get_media_duration(file_path):
    """Accurately and quickly extracts duration in seconds using ffprobe, fallback to pydub."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    ffprobe_bin = FFPROBE_PATH if os.path.exists(FFPROBE_PATH) else "ffprobe"
    try:
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            val = float(res.stdout.strip())
            if val > 0:
                return val
    except Exception:
        pass
    try:
        return AudioSegment.from_file(file_path).duration_seconds
    except Exception:
        return 120.0

def has_audio_stream(file_path):
    """Returns True if the media file contains at least one audio stream."""
    if not file_path or not os.path.exists(file_path):
        return False
    ffprobe_bin = FFPROBE_PATH if os.path.exists(FFPROBE_PATH) else "ffprobe"
    try:
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return "audio" in res.stdout.lower()
    except Exception:
        return False

def get_next_background_video():
    """
    Scans the 'bg' folder (and fallback: 'background_videos')
    for video files (.mp4, .mov, .mkv, .webm, .avi).
    Rotates through them sequentially using 'last_bg_video_index.txt'.
    """
    search_dirs = ["bg", "background_videos"]
    valid_exts = ('.mp4', '.mov', '.mkv', '.webm', '.avi')
    
    candidate_dir = None
    files = []
    
    for d in search_dirs:
        dir_path = os.path.join(os.getcwd(), d) if not os.path.isabs(d) else d
        if os.path.exists(dir_path):
            found = sorted([os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(valid_exts)])
            if found:
                candidate_dir = dir_path
                files = found
                break
                
    if not files:
        os.makedirs(os.path.join(os.getcwd(), "bg"), exist_ok=True)
        return None
        
    tracker_file = os.path.join(os.getcwd(), "last_bg_video_index.txt")
    index = 0
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                index = int(f.read().strip())
        except Exception:
            index = 0
            
    if index >= len(files):
        index = 0
        
    selected_file = files[index]
    next_index = (index + 1) % len(files)
    
    try:
        with open(tracker_file, "w") as f:
            f.write(str(next_index))
    except Exception:
        pass
        
    print(f"   > 🎥 Loaded Background Video from '{os.path.basename(candidate_dir)}': {os.path.basename(selected_file)} (Clip {index + 1}/{len(files)})", flush=True)
    return selected_file

def get_next_background_music():
    """
    Scans 'bg', 'background_music' for audio/music files (.mp3, .wav, .m4a, .mp4, .mov).
    Rotates through them sequentially using 'last_bg_index.txt'.
    """
    search_dirs = ["bg", "background_music"]
    valid_exts = ('.mp3', '.wav', '.m4a', '.mp4', '.mov')
    
    files = []
    for d in search_dirs:
        dir_path = os.path.join(os.getcwd(), d) if not os.path.isabs(d) else d
        if os.path.exists(dir_path):
            found = sorted([os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(valid_exts)])
            if found:
                files = found
                break
                
    if not files:
        return None
        
    tracker_file = os.path.join(os.getcwd(), "last_bg_index.txt")
    index = 0
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                index = int(f.read().strip())
        except Exception:
            index = 0
            
    if index >= len(files):
        index = 0
        
    selected_file = files[index]
    next_index = (index + 1) % len(files)
    
    try:
        with open(tracker_file, "w") as f:
            f.write(str(next_index))
    except Exception:
        pass
        
    return selected_file

def render_long_form_video(image_path, audio_path, srt_path, bg_music_path, final_output_path, sub_size="24", sub_color="Yellow", sub_position="Bottom", hardware_mode="Standard", device="cpu", bg_music_enabled=True, progress_callback=None, bg_video_path=None, use_image_bg=False):
    # If explicitly configured to use custom image background, suppress video background
    if use_image_bg:
        bg_video_path = None
    elif not bg_video_path:
        # Auto-resolve background video from 'bg' folder if not explicitly supplied
        bg_video_path = get_next_background_video()

    # Enforce strict local directory routing to purge any legacy AppData path inputs
    if srt_path and not os.path.exists(srt_path):
        srt_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(srt_path))
    if audio_path and not os.path.exists(audio_path):
        audio_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(audio_path))
    if not audio_path or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        print(f"   > ❌ Video Composition Error: Audio file '{audio_path}' does not exist or is 0 bytes.", flush=True)
        print("   > 📌 Audio generation failed or was skipped because the script was empty.", flush=True)
        return False
    if image_path and not os.path.exists(image_path):
        image_path = os.path.join(os.getcwd(), "lf_assets", os.path.basename(image_path))
    if final_output_path and not os.path.isabs(final_output_path):
        final_output_path = os.path.join(os.getcwd(), "lf_output", os.path.basename(final_output_path))

    total_gb, allocated_gb, _ = _get_ram_allocation()
    has_nvidia, gpu_name, vram_gb = get_nvidia_gpu_info()
    gpu_banner = f" | [+] GPU: {gpu_name or 'NVIDIA GTX 1660 Super'} ({vram_gb}GB VRAM - NVENC/CUDA ⚡)" if has_nvidia or device == "cuda" else ""
    print(f"   > 🎬 Booting FFmpeg Render Engine | Dynamic RAM: {allocated_gb}GB / {total_gb}GB (75%){gpu_banner}", flush=True)
    ffmpeg_exe = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"

    # Calculate audio duration precisely
    audio_dur = get_media_duration(audio_path)
    if audio_dur <= 0:
        audio_dur = 120.0
    dur_str = f"{audio_dur:.2f}"

    # SSA Primary Colors: Yellow, White, Green, Cyan
    COLOR_MAP = {
        "Yellow": "&H0000FFFF",
        "White": "&H00FFFFFF",
        "Green": "&H0000FF00",
        "Cyan": "&H00FFFF00"
    }
    ssa_color = COLOR_MAP.get(sub_color, "&H0000FFFF")

    # Determine video mode: Moving Background Video (from 'bg' folder) OR Still Image
    has_bg_video = bool(bg_video_path and os.path.exists(bg_video_path))
    if has_bg_video:
        print(f"   > 🎥 Moving Background Video ACTIVE: {os.path.basename(bg_video_path)} (from bg folder)", flush=True)
        # Input 0: Background video looped infinitely (bounded by -t dur_str on output)
        cmd = [
            ffmpeg_exe,
            '-stream_loop', '-1',
            '-i', bg_video_path,
            '-i', audio_path
        ]
        video_filter = "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=24"
        safe_srt_temp = None
        if srt_path and os.path.exists(srt_path):
            try:
                import shutil
                safe_srt_temp = os.path.join(TEMP_DIR, "render_subs_temp.srt")
                shutil.copyfile(srt_path, safe_srt_temp)
                clean_srt = os.path.abspath(safe_srt_temp).replace("\\", "/")
                clean_srt = clean_srt.replace(":", "\\:")
                video_filter += f",subtitles=filename='{clean_srt}':force_style='Alignment=2,FontSize={sub_size},PrimaryColour={ssa_color},Outline=2,Shadow=1,MarginV=20,WrapStyle=2'"
            except Exception as se:
                print(f"   > ⚠️ Warning preparing subtitle filter: {se}", flush=True)
        video_filter += "[vout]"

        # Audio handling for moving background video
        bg_has_audio = bg_music_enabled and has_audio_stream(bg_video_path)
        if bg_has_audio:
            print(f"   > 🎵 Mixing audio stream from background video: {os.path.basename(bg_video_path)} (volume: 8%)", flush=True)
            filter_complex = (
                f"[1:a]aresample=48000,volume=1.0[a1];[0:a]aresample=48000,volume=0.08[a2];"
                f"[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[aout];"
                f"{video_filter}"
            )
            audio_map = '[aout]'
        elif bg_music_enabled and bg_music_path and os.path.exists(bg_music_path) and bg_music_path != bg_video_path:
            print(f"   > 🎵 Injecting & Looping Background Music: {os.path.basename(bg_music_path)}", flush=True)
            cmd.extend(['-stream_loop', '-1', '-i', bg_music_path])
            filter_complex = (
                f"[1:a]aresample=48000,volume=1.0[a1];[2:a]aresample=48000,volume=0.08[a2];"
                f"[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[aout];"
                f"{video_filter}"
            )
            audio_map = '[aout]'
        else:
            print("   > 🎵 Voiceover audio stream only (silent background video).", flush=True)
            filter_complex = f"[1:a]aresample=48000[aout];{video_filter}"
            audio_map = '[aout]'
    else:
        print(f"   > 🖼️ Still Image Video Mode ACTIVE: {os.path.basename(image_path)}", flush=True)
        cmd = [
            ffmpeg_exe,
            '-loop', '1',
            '-t', dur_str,
            '-framerate', '24',
            '-i', image_path,
            '-i', audio_path
        ]
        video_filter = "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
        safe_srt_temp = None
        if srt_path and os.path.exists(srt_path):
            try:
                import shutil
                safe_srt_temp = os.path.join(TEMP_DIR, "render_subs_temp.srt")
                shutil.copyfile(srt_path, safe_srt_temp)
                clean_srt = os.path.abspath(safe_srt_temp).replace("\\", "/")
                clean_srt = clean_srt.replace(":", "\\:")
                video_filter += f",subtitles=filename='{clean_srt}':force_style='Alignment=2,FontSize={sub_size},PrimaryColour={ssa_color},Outline=2,Shadow=1,MarginV=20,WrapStyle=2'"
            except Exception as se:
                print(f"   > ⚠️ Warning preparing subtitle filter: {se}", flush=True)
        video_filter += "[vout]"

        if bg_music_enabled and bg_music_path and os.path.exists(bg_music_path):
            print(f"   > 🎵 Injecting & Looping Background Music: {os.path.basename(bg_music_path)}", flush=True)
            cmd.extend(['-stream_loop', '-1', '-i', bg_music_path])
            filter_complex = (
                f"[1:a]aresample=48000,volume=1.0[a1];[2:a]aresample=48000,volume=0.08[a2];"
                f"[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[aout];"
                f"{video_filter}"
            )
            audio_map = '[aout]'
        else:
            print("   > 🎵 Background music disabled or missing. Rendering voiceover audio stream only.", flush=True)
            filter_complex = f"[1:a]aresample=48000[aout];{video_filter}"
            audio_map = '[aout]'

    # Dynamic FFmpeg thread count: scale with CPU cores
    logical_cores = psutil.cpu_count(logical=True) or 4
    threads = str(logical_cores)

    # Build primary and fallback encoder configurations:
    has_nvidia, gpu_name, vram_gb = get_nvidia_gpu_info()
    gpu_label = gpu_name or "NVIDIA GPU"

    # Pre-test NVENC so we NEVER hang or crash trying an unsupported hardware encoder
    nvenc_ok = False
    if device != "cpu" and (has_nvidia or device == "cuda"):
        try:
            nvenc_ok = is_nvenc_functional()
        except Exception:
            nvenc_ok = False

        if not nvenc_ok:
            print(f"   > ℹ️ GPU Detected: {gpu_label}, but NVENC encoding is unavailable on current driver.", flush=True)
            print(f"   > 🔄 Automatic Fallback: Using multi-threaded CPU rendering (libx264) to prevent crash.", flush=True)
        else:
            print(f"   > ⚡ Prioritizing NVIDIA NVENC Hardware Encoding ({gpu_label})", flush=True)

    encoders_to_try = []
    if nvenc_ok:
        is_older_gpu = any(k in gpu_label.lower() for k in ["680", "670", "660", "650", "750", "760", "770", "780", "gtx 6", "gtx 7"])
        if not is_older_gpu:
            encoders_to_try.append((f'NVIDIA NVENC Hardware Engine ({gpu_label})', ['-c:v', 'h264_nvenc', '-preset', 'fast', '-rc', 'vbr', '-cq', '23', '-b:v', '0', '-spatial-aq', '1']))
        encoders_to_try.append((f'NVIDIA NVENC Universal Compatibility ({gpu_label})', ['-c:v', 'h264_nvenc', '-preset', 'fast', '-cq', '23']))
        encoders_to_try.append(('NVIDIA NVENC Basic (h264_nvenc)', ['-c:v', 'h264_nvenc']))

    if device == "amf":
        encoders_to_try.append(('AMD AMF (h264_amf)', ['-c:v', 'h264_amf']))

    # CPU Encoders - ALWAYS included as reliable primary or fallback
    if has_bg_video:
        encoders_to_try.append(('High-Speed Video Engine (libx264 CPU fallback)', ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23']))
    else:
        encoders_to_try.append(('High-Speed Stillimage Engine (libx264 CPU fallback)', ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '23']))

    for enc_name, enc_args in encoders_to_try:
        print(f"   > 🎬 Starting Video Rendering via: {enc_name} (Threads: {threads})...", flush=True)
        full_cmd = list(cmd)
        full_cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[vout]',
            '-map', audio_map
        ])
        full_cmd.extend(enc_args)
        full_cmd.extend([
            '-r', '24',
            '-pix_fmt', 'yuv420p',
            '-threads', threads,
            '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
            '-t', dur_str,
            '-progress', 'pipe:1', '-y', final_output_path
        ])

        process = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace'
        )

        stderr_lines = collections.deque(maxlen=40)
        def _read_stderr():
            try:
                for eline in iter(process.stderr.readline, ''):
                    if eline:
                        sline = eline.strip()
                        stderr_lines.append(sline)
                        if any(w in sline.lower() for w in ["fontconfig", "loading fonts", "building font", "nvenc"]):
                            print(f"     [FFmpeg Engine] {sline}", flush=True)
            except Exception:
                pass

        err_thread = threading.Thread(target=_read_stderr, daemon=True)
        err_thread.start()

        last_callback_pct = -1
        last_print_pct = -1
        last_print_time = 0.0
        current_speed = ""
        current_fps = ""

        # Kick off progress bar in GUI immediately so it never stays at "Idle"
        if progress_callback:
            progress_callback(0, f"Rendering Video (0%) | {enc_name.split('(')[0].strip()} Starting...")

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.strip()
                if line.startswith("speed="):
                    sp_val = line.split("=")[1].strip()
                    if sp_val and sp_val != "N/A":
                        current_speed = sp_val
                elif line.startswith("fps="):
                    fps_val = line.split("=")[1].strip()
                    if fps_val and fps_val not in ("0", "0.0"):
                        current_fps = fps_val
                elif line.startswith("out_time_us="):
                    try:
                        val = line.split("=")[1].strip()
                        if val.isdigit():
                            us = int(val)
                            cur_sec = us / 1_000_000.0
                            if audio_dur > 0:
                                pct = min(99, int((cur_sec / audio_dur) * 100))
                                now = time.time()
                                cur_m, cur_s = int(cur_sec // 60), int(cur_sec % 60)
                                tot_m, tot_s = int(audio_dur // 60), int(audio_dur % 60)

                                # Calculate remaining ETA in seconds
                                eta_str = ""
                                if current_speed:
                                    try:
                                        spd_num = float(current_speed.replace('x', ''))
                                        if spd_num > 0.1:
                                            rem_sec = max(0, int((audio_dur - cur_sec) / spd_num))
                                            rem_m, rem_s = rem_sec // 60, rem_sec % 60
                                            eta_str = f"{rem_m:02d}:{rem_s:02d}"
                                    except Exception:
                                        pass

                                rate_display = current_speed if current_speed else "Active"
                                if current_fps:
                                    rate_display += f" ({current_fps} FPS)"

                                # 1. Smooth GUI Progress Bar: Update on every 1% change with clear Proceeding Rate
                                if progress_callback and pct != last_callback_pct:
                                    last_callback_pct = pct
                                    gui_label = f"Rendering Video {pct}% | Rate: {rate_display} | {cur_m:02d}:{cur_s:02d}/{tot_m:02d}:{tot_s:02d}"
                                    if eta_str:
                                        gui_label += f" | ETA {eta_str}"
                                    progress_callback(pct, gui_label)

                                # 2. Live Console Log: Visual ASCII progress bar displaying Proceeding Rate
                                if pct != last_print_pct and ((pct - last_print_pct) >= 2 or (now - last_print_time) >= 1.5):
                                    last_print_pct = pct
                                    last_print_time = now
                                    bar_len = 25
                                    filled = int(bar_len * pct / 100)
                                    empty = bar_len - filled
                                    bar_str = "█" * filled + "░" * empty

                                    rate_info = f"Rate: {current_speed}" if current_speed else "Rate: Active"
                                    if current_fps:
                                        rate_info += f" ({current_fps} FPS)"
                                    
                                    time_info = f"{cur_m:02d}:{cur_s:02d}/{tot_m:02d}:{tot_s:02d}"
                                    eta_info = f"ETA: {eta_str}" if eta_str else ""
                                    details = " | ".join(filter(None, [rate_info, time_info, eta_info]))

                                    print(f"[+] 🎬 Render Progress: [{bar_str}] {pct:2d}% | {details}", flush=True)
                    except Exception:
                        pass

        process.wait()
        err_thread.join(timeout=2.0)

        if process.returncode == 0:
            print(f"[+] 🎬 Video Render Progress: [{'█' * 25}] 100% (Render Complete)", flush=True)
            if progress_callback:
                progress_callback(100, "Rendering Complete (100%)")
            print(f"   > ✅ Final Video successfully rendered: {final_output_path}", flush=True)
            return True
        else:
            print(f"   > ⚠️ Encoder {enc_name} failed (exit code {process.returncode}).", flush=True)
            if "nvenc" in enc_name.lower():
                global _nvenc_tested
                _nvenc_tested = False
            if stderr_lines:
                print("   > 📋 Diagnostics (last FFmpeg output):", flush=True)
                for el in list(stderr_lines)[-5:]:
                    print(f"     | {el}", flush=True)
            print("   > 🔄 Automatically falling back to next encoder (CPU libx264)...", flush=True)

    if safe_srt_temp and os.path.exists(safe_srt_temp):
        try: os.remove(safe_srt_temp)
        except Exception: pass

    print("   > ❌ FFmpeg Render Failed across all encoders.", flush=True)
    return False