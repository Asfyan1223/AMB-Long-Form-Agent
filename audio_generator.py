import sys

# --- GLOBAL ENCODING FIX ---
# Force Windows terminal to support UTF-8 emojis without crashing
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
# ---------------------------

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
import imageio_ffmpeg
import psutil
import torch
import numpy as np
import soundfile as sf
from silero_manager import SileroTTSManager, get_silero_manager, sync_generate_silero

# Maximize PyTorch CPU intra-op multi-threading
_num_cores = psutil.cpu_count(logical=True) or 4
torch.set_num_threads(_num_cores)

TEMP_DIR = os.path.join(os.getcwd(), "lf_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

import gc
import threading

# Silero Neural Voices mapping
VOICE_ACTORS = {
    "Xenia (Default Female)": "xenia",
    "Baya (Warm Female)": "baya",
    "Kseniya (Clear Female)": "kseniya",
    "Aidar (Deep Male)": "aidar",
    "Eugene (Calm Male)": "eugene",
    # Backward-compatible fallbacks for legacy profile settings
    "English (US) Bella (Premium Female)": "xenia",
    "Urdu Bella (Premium Female)": "xenia",
    "Russian Bella (Premium Female)": "xenia",
    "German Bella (Premium Female)": "xenia",
    "Arabic Bella (Premium Female)": "xenia",
    "US Male Deep": "aidar"
}
# Default Voice Mapping
TTS_VOICES = {
    "English": "xenia",
    "Arabic": "xenia",
    "German": "xenia",
    "Russian": "xenia",
    "Urdu": "xenia"
}

# Map Language Names to 2-letter ISO Codes for Whisper
LANG_CODES = {
    "English": "en",
    "German": "de",
    "Russian": "ru",
    "Arabic": "ar",
    "Urdu": "ur"
}

# Backward compatibility alias
sync_generate_kokoro = sync_generate_silero

async def generate_tts(text_file, language, output_audio_path, voice_actor=None, progress_callback=None):
    """
    Synthesizes speech using Silero Neural TTS and saves 48000 Hz master audio.
    """
    mgr = get_silero_manager()
    success = await asyncio.to_thread(
        mgr.generate_from_script,
        script_path_or_text=text_file,
        output_path=output_audio_path,
        speaker=voice_actor,
        sample_rate=48000,
        language=language,
        progress_callback=progress_callback
    )
    return success
