import os

FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\ffmpeg\bin\ffprobe.exe"

# Set environment variable to force libraries like imageio_ffmpeg / moviepy to use this binary
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_PATH

# Fallback safety check to alert the developer immediately if the drive path is wrong
if not os.path.exists(FFMPEG_PATH):
    print(f"[CRITICAL] FFmpeg binary not found at {FFMPEG_PATH}. Video rendering will fail.")

import asyncio
import subprocess
import edge_tts
import imageio_ffmpeg
import math
from faster_whisper import WhisperModel
from pydub import AudioSegment

TEMP_DIR = "lf_temp"
OUTPUT_DIR = "lf_output"
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
    
    cpu_threads = 4
    if hardware_mode == "Low-End PC (Fastest)":
        cpu_threads = 2
    elif hardware_mode == "Standard":
        cpu_threads = 4
    elif hardware_mode == "High-End Workstation":
        cpu_threads = 8
        
    print(f"   > ⚙️ Whisper Threads Allocated: {cpu_threads}")
    
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
    print("   > 🎬 Booting FFmpeg Render Engine (Low-RAM Mode)...")
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
 
    preset = "veryfast"
    threads = "4"
    if hardware_mode == "Low-End PC (Fastest)":
        preset = "ultrafast"
        threads = "2"
    elif hardware_mode == "Standard":
        preset = "veryfast"
        threads = "4"
    elif hardware_mode == "High-End Workstation":
        preset = "fast"
        threads = "8"

    # Select the optimal video encoder based on the system hardware profile
    if device == "cuda":
        print("   > 🚀 Dynamic GPU Encoder: NVIDIA NVENC (h264_nvenc) selected.")
        video_codec_args = ['-c:v', 'h264_nvenc', '-preset', 'p3', '-rc', 'constqp', '-qp', '23']
    elif device == "amf":
        print("   > 🚀 Dynamic GPU Encoder: AMD AMF (h264_amf) selected.")
        video_codec_args = ['-c:v', 'h264_amf']
    else:
        print("   > 🐌 GPU Acceleration Unavailable. Using libx264 CPU encoder.")
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