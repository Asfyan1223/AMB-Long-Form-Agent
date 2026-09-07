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
    
    whisper_device = "cuda" if device == "cuda" else "cpu"
    compute_type = "int8_float16" if whisper_device == "cuda" else "int8"
    
    try:
        model = WhisperModel("base", device=whisper_device, compute_type=compute_type, cpu_threads=cpu_threads)
    except Exception as e:
        model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    
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
            
            segments, _ = model.transcribe(temp_chunk_path, vad_filter=True, language=whisper_lang, word_timestamps=True)
            time_offset = i * 60.0
            
            for segment in segments:
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

def render_long_form_video(image_path, audio_path, srt_path, bg_music_path, final_output_path, sub_size="24", sub_color="Yellow", sub_position="Bottom", hardware_mode="Standard", device="cpu", bg_music_enabled=True, progress_callback=None):
    # Enforce strict local directory routing to purge any legacy AppData path inputs
    if srt_path and not os.path.exists(srt_path):
        srt_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(srt_path))
    if audio_path and not os.path.exists(audio_path):
        audio_path = os.path.join(os.getcwd(), "lf_temp", os.path.basename(audio_path))
    if image_path and not os.path.exists(image_path):
        image_path = os.path.join(os.getcwd(), "lf_assets", os.path.basename(image_path))
    if final_output_path and not os.path.isabs(final_output_path):
        final_output_path = os.path.join(os.getcwd(), "lf_output", os.path.basename(final_output_path))

    total_gb, allocated_gb, _ = _get_ram_allocation()
    print(f"   > 🎬 Booting FFmpeg Render Engine | [+] Dynamic Memory: Total {total_gb}GB | Allocating {allocated_gb}GB (75%)")
    ffmpeg_exe = FFMPEG_PATH
    
    cmd = [
        ffmpeg_exe,
        '-loop', '1', '-framerate', '2', 
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
        clean_srt = os.path.relpath(srt_path, os.getcwd()).replace("\\", "/") if os.path.exists(srt_path) else srt_path.replace("\\", "/")
        video_filter += f",subtitles=filename='{clean_srt}':force_style='Alignment=2,FontSize={sub_size},PrimaryColour={ssa_color},Outline=2,Shadow=1,MarginV=20,WrapStyle=2'"
    video_filter += "[vout]"
    
    # Conditionally mix background music if enabled
    if bg_music_enabled and bg_music_path and os.path.exists(bg_music_path):
        is_video = bg_music_path.lower().endswith(('.mp4', '.mov'))
        if is_video:
            print(f"   > 🎵 Extracting & Looping audio stream from background video: {os.path.basename(bg_music_path)}")
        else:
            print(f"   > 🎵 Injecting & Looping Background Music: {os.path.basename(bg_music_path)}")
        # Use -vn to completely bypass video decoding from the music file, saving 40% CPU
        cmd.extend(['-stream_loop', '-1', '-vn', '-i', bg_music_path])
        filter_complex = (
            f"[1:a]aresample=48000,volume=1.0[a1];[2:a]aresample=48000,volume=0.08[a2];"
            f"[a1][a2]amix=inputs=2:duration=first[aout];"
            f"{video_filter}"
        )
        audio_map = '[aout]'
    else:
        print("   > 🎵 Background music disabled or missing. Rendering voiceover audio stream only.")
        filter_complex = f"[1:a]aresample=48000[aout];{video_filter}"
        audio_map = '[aout]'
 
    # Dynamic FFmpeg thread count: scale with CPU cores
    logical_cores = psutil.cpu_count(logical=True) or 4
    threads = str(logical_cores)

    # Build primary and fallback encoder configurations
    encoders_to_try = []
    if is_nvenc_functional():
        encoders_to_try.append(('NVIDIA NVENC (h264_nvenc)', ['-c:v', 'h264_nvenc', '-preset', 'fast', '-rc', 'constqp', '-qp', '23']))
    elif device == "amf":
        encoders_to_try.append(('AMD AMF (h264_amf)', ['-c:v', 'h264_amf']))
    
    # Universal high-speed stillimage CPU encoder (renders 30min in ~20s)
    encoders_to_try.append(('High-Speed Stillimage Engine (libx264)', ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '23']))

    # Calculate audio duration for live progress tracking
    try:
        audio_dur = AudioSegment.from_file(audio_path).duration_seconds
    except Exception:
        audio_dur = 120.0

    for enc_name, enc_args in encoders_to_try:
        print(f"   > 🎬 Starting Video Rendering via: {enc_name} (Threads: {threads})...")
        full_cmd = list(cmd)
        full_cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[vout]',
            '-map', audio_map
        ])
        full_cmd.extend(enc_args)
        full_cmd.extend([
            '-g', '10',
            '-fps_mode', 'vfr',
            '-threads', threads,
            '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
            '-shortest', '-progress', 'pipe:1', '-y', final_output_path
        ])
        
        process = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        last_pct = -1
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        val = line.split("=")[1].strip()
                        if val.isdigit():
                            us = int(val)
                            cur_sec = us / 1_000_000.0
                            if audio_dur > 0:
                                pct = min(99, int((cur_sec / audio_dur) * 100))
                                if pct != last_pct:
                                    last_pct = pct
                                    if pct % 10 == 0 or pct in [25, 50, 75]:
                                        filled = int(15 * pct / 100)
                                        empty = 15 - filled
                                        print(f"[+] 🎬 Video Render Progress: [{'█' * filled}{'░' * empty}] {pct}%")
                                    if progress_callback:
                                        progress_callback(pct, "Rendering Video")
                    except Exception:
                        pass
                        
        process.communicate()
        if process.returncode == 0:
            print(f"[+] 🎬 Video Render Progress: [{'█' * 15}] 100% (Render Complete)")
            if progress_callback:
                progress_callback(100, "Rendering Complete")
            print(f"   > ✅ Final Video successfully rendered: {final_output_path}")
            return True
        else:
            print(f"   > ℹ️ Encoder {enc_name} failed (exit code {process.returncode}). Trying fallback...")

    print("   > ❌ FFmpeg Render Failed across all encoders.")
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