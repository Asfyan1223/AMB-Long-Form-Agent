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

def detect_nvidia_gpu():
    """Returns True if nvidia-smi reports a GPU, False otherwise."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            gpu_name = result.stdout.strip().splitlines()[0]
            print(f"[+] Nvidia GPU Detected: Using NVENC Hardware Acceleration ({gpu_name})")
            return True
    except Exception:
        pass
    print("[-] No GPU Detected: Falling back to CPU rendering (libx264)")
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

def generate_srt(audio_path, srt_output_path, hardware_mode="Standard", device="cpu", language="English"):
    print("   > 🧠 Running Whisper AI to generate .srt Subtitles (60s Chunk Loop)...")
    
    # Dynamic thread allocation: scale with physical CPU count, cap to 75%-RAM tier
    total_gb, allocated_gb, _ = _get_ram_allocation()
    logical_cores = psutil.cpu_count(logical=True) or 4
    if hardware_mode == "Low-End PC (Fastest)":
        cpu_threads = max(2, logical_cores // 4)
    elif hardware_mode == "High-End Workstation":
        cpu_threads = min(logical_cores, 16)
    else:  # Standard / fallback
        cpu_threads = max(2, logical_cores // 2)
        
    print(f"   > ⚙️ Whisper Threads Allocated: {cpu_threads} | RAM Budget: {allocated_gb}GB / {total_gb}GB (75%)") 
    
    # Configure Whisper for dynamic GPU acceleration
    whisper_device = "cuda" if device == "cuda" else "cpu"
    compute_type = "int8_float16" if whisper_device == "cuda" else "int8"
    
    try:
        model = WhisperModel("base", device=whisper_device, compute_type=compute_type, cpu_threads=cpu_threads)
        print(f"   > ⚙️ Whisper GPU initialized successfully on device: {whisper_device}")
    except Exception as e:
        print(f"   > ⚠️ Whisper GPU initialization failed: {e}. Falling back to CPU mode.")
        model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    
    audio = AudioSegment.from_file(audio_path)
    chunk_length_ms = 60 * 1000
    total_chunks = math.ceil(len(audio) / chunk_length_ms)
    
    if os.path.exists(srt_output_path):
        try:
            os.remove(srt_output_path)
        except:
            pass
            
    subtitle_index = 1
    temp_chunk_path = "lf_temp/temp_whisper_chunk.wav"
    
    whisper_lang = LANG_CODES.get(language, "en")
    
    with open(srt_output_path, "a", encoding="utf-8") as f:
        for i in range(total_chunks):
            print(f"   > 🧠 Transcribing chunk {i+1}/{total_chunks} in language: '{whisper_lang}'...")
            chunk = audio[i * chunk_length_ms : (i + 1) * chunk_length_ms]
            chunk.export(temp_chunk_path, format="wav")
            
            # Pass language code explicitly to bypass auto-detect overhead and request word timestamps
            segments, _ = model.transcribe(temp_chunk_path, vad_filter=True, language=whisper_lang, word_timestamps=True)
            time_offset = i * 60.0
            
            for segment in segments:
                # Group words into chunks of maximum 8 words
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
                    # Proportional fallback splitting if word timestamps are not populated
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
        try:
            os.remove(temp_chunk_path)
            print("   > 🧹 Cleaned up temporary Whisper chunk.")
        except Exception as e:
            print(f"   > ⚠️ Warning: Failed to delete temp Whisper chunk: {e}")
            
    print(f"   > ✅ Subtitle file generated: {srt_output_path}")

def render_long_form_video(image_path, audio_path, srt_path, bg_music_path, final_output_path, sub_size="24", sub_color="Yellow", sub_position="Bottom", hardware_mode="Standard", device="cpu", bg_music_enabled=True):
    # Enforce strict local directory routing to purge any legacy AppData path inputs
    if srt_path:
        srt_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(srt_path))
    if audio_path:
        audio_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(audio_path))
    if image_path:
        image_path = os.path.join(os.getcwd(), "lf_assets", os.path.basename(image_path))
    if final_output_path:
        final_output_path = os.path.join(os.getcwd(), "lf_output", os.path.basename(final_output_path))

    total_gb, allocated_gb, _ = _get_ram_allocation()
    print(f"   > 🎬 Booting FFmpeg Render Engine | [+] Dynamic Memory: Total {total_gb}GB | Allocating {allocated_gb}GB (75%)")
    ffmpeg_exe = FFMPEG_PATH
    
    cmd = [
        ffmpeg_exe,
        '-loop', '1', '-framerate', '30', 
        '-i', image_path,
        '-i', audio_path
    ]
    
    # Enforce locked alignment=2 (bottom-center) for consistent single-line positioning
    alignment = "2"
    
    # SSA Primary Colors: Yellow (constqp/hex conversion), White, Green, Cyan
    COLOR_MAP = {
        "Yellow": "&H0000FFFF",
        "White": "&H00FFFFFF",
        "Green": "&H0000FF00",
        "Cyan": "&H00FFFF00"
    }
    ssa_color = COLOR_MAP.get(sub_color, "&H0000FFFF")

    # Build video filter with or without subtitles
    video_filter = "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
    if srt_path:
        import sys
        # 1. Force the absolute path
        abs_srt_path = os.path.abspath(srt_path)

        # 2. INTEGRITY CHECK: Stop the loop if the file literally doesn't exist
        if not os.path.exists(abs_srt_path):
            print("\n=======================================================")
            print("🚨 CRITICAL ERROR: SUBTITLE FILE MISSING 🚨")
            print(f"Path: {abs_srt_path}")
            print("Whisper failed to create the .srt file. Halting render!")
            print("=======================================================\n")
            sys.exit()

        # 3. The Ultimate Windows FFmpeg Escaping
        ffmpeg_safe_srt = abs_srt_path.replace("\\", "/").replace(":", "\\:")
        # Disables text wrapping completely by passing WrapStyle=2,Flm=0 and locking Alignment=2
        video_filter += f",subtitles='{ffmpeg_safe_srt}':force_style='Alignment=2,FontSize={sub_size},PrimaryColour={ssa_color},Outline=2,Shadow=1,MarginV=20,WrapStyle=2,Flm=0'"
    video_filter += "[vout]"
    
    # Conditionally mix background music if enabled
    if bg_music_enabled and bg_music_path and os.path.exists(bg_music_path):
        is_video = bg_music_path.lower().endswith(('.mp4', '.mov'))
        if is_video:
            print(f"   > 🎵 Extracting & Looping audio stream from background video: {os.path.basename(bg_music_path)}")
        else:
            print(f"   > 🎵 Injecting & Looping Background Music: {os.path.basename(bg_music_path)}")
        cmd.extend(['-stream_loop', '-1', '-i', bg_music_path])
        filter_complex = (
            f"[1:a]volume=1.0[a1];[2:a]volume=0.08[a2];"
            f"[a1][a2]amix=inputs=2:duration=first[aout];"
            f"{video_filter}"
        )
        audio_map = '[aout]'
    else:
        print("   > 🎵 Background music disabled or missing. Rendering voiceover audio stream only.")
        filter_complex = f"{video_filter}"
        audio_map = '1:a'
 
    # Dynamic FFmpeg thread count: scale with CPU cores
    logical_cores = psutil.cpu_count(logical=True) or 4
    if hardware_mode == "Low-End PC (Fastest)":
        preset = "ultrafast"
        threads = str(max(2, logical_cores // 4))
    elif hardware_mode == "High-End Workstation":
        preset = "fast"
        threads = str(min(logical_cores, 16))
    else:  # Standard / fallback
        preset = "veryfast"
        threads = str(max(2, logical_cores // 2))

    # Select the optimal video encoder: CUDA > AMF > nvidia-smi re-check > CPU
    if device == "cuda":
        print("   > 🚀 Dynamic GPU Encoder: NVIDIA NVENC (h264_nvenc) selected.")
        video_codec_args = ['-c:v', 'h264_nvenc', '-preset', 'p3', '-rc', 'constqp', '-qp', '23']
    elif device == "amf":
        print("   > 🚀 Dynamic GPU Encoder: AMD AMF (h264_amf) selected.")
        video_codec_args = ['-c:v', 'h264_amf']
    elif detect_nvidia_gpu():
        # CPU mode but nvidia-smi confirms an NVENC-capable GPU is present
        video_codec_args = ['-c:v', 'h264_nvenc', '-preset', 'p3', '-rc', 'constqp', '-qp', '23']
    else:
        video_codec_args = ['-c:v', 'libx264', '-preset', preset, '-tune', 'stillimage', '-crf', '23']

    print(f"   > ⚙️ FFmpeg Allocation: Preset={preset}, Threads={threads}")
    cmd.extend([
        '-filter_complex', filter_complex,
        '-map', '[vout]',
        '-map', audio_map
    ])
    cmd.extend(video_codec_args)
    cmd.extend([
        '-g', '300',
        '-vsync', '2',
        '-threads', threads,
        '-c:a', 'aac', '-b:a', '128k',
        '-shortest', '-y', final_output_path
    ])
    
    process = subprocess.run(cmd, stdout=None, stderr=None)
    
    if process.returncode == 0:
        print(f"   > ✅ Final 1-Hour Video successfully rendered: {final_output_path}")
        return True
    else:
        print("   > ❌ FFmpeg Render Failed.")
        return False

def get_next_background_music():
    bg_dir = "background_music"
    os.makedirs(bg_dir, exist_ok=True)
    valid_exts = ('.mp3', '.wav', '.mp4', '.mov')
    if not os.path.exists(bg_dir):
        return None
    files = sorted([os.path.join(bg_dir, f) for f in os.listdir(bg_dir) if f.lower().endswith(valid_exts)])
    if not files:
        return None
        
    tracker_file = "last_bg_index.txt"
    index = 0
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                index = int(f.read().strip())
        except:
            index = 0
            
    if index >= len(files):
        index = 0
        
    selected_file = files[index]
    next_index = (index + 1) % len(files)
    
    try:
        with open(tracker_file, "w") as f:
            f.write(str(next_index))
    except:
        pass
        
    return selected_file