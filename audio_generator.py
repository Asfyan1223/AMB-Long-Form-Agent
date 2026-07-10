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
import numpy as np
import soundfile as sf
from kokoro import KPipeline

TEMP_DIR = os.path.join(os.getcwd(), "lf_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize globally to avoid 10-second load time on every request
# We use 'a' by default (American English). We lazy-load 'b' (British English) if needed.
pipeline_a = KPipeline(lang_code='a')
pipeline_b = None

def get_pipeline(voice):
    global pipeline_b
    if voice.startswith('b'):
        if pipeline_b is None:
            print("   > 🚀 Initializing British English Kokoro Pipeline...")
            pipeline_b = KPipeline(lang_code='b')
        return pipeline_b
    return pipeline_a

def sync_generate_kokoro(text, voice, output_path):
    """Synchronously generates audio from text using Kokoro pipeline and soundfile."""
    active_pipeline = get_pipeline(voice)
    generator = active_pipeline(text, voice=voice, speed=1.0)
    
    audio_chunks = []
    for gs, ps, audio in generator:
        if audio is not None and len(audio) > 0:
            audio_chunks.append(audio)
            
    if not audio_chunks:
        raise RuntimeError("Kokoro generated no audio data.")
        
    full_audio = np.concatenate(audio_chunks)
    sf.write(output_path, full_audio, 24000)

# Map Voice Actors to Kokoro Neural Voices
VOICE_ACTORS = {
    "English (US) Male": "am_adam",
    "English (US) Female": "af_sarah",
    "English (UK) Male": "bm_george",
    "English (UK) Female": "bf_emma",
    "German Male": "am_adam",
    "German Female": "af_sarah",
    "Russian Male": "am_adam",
    "Russian Female": "af_sarah",
    "Arabic Male": "am_adam",
    "Arabic Female": "af_sarah",
    "Urdu Male": "am_adam",
    "Urdu Female": "af_sarah"
}

# Map UI languages to defaults
TTS_VOICES = {
    "English": "af_sarah",
    "Arabic": "af_sarah",
    "German": "af_sarah",
    "Russian": "af_sarah",
    "Urdu": "af_sarah"
}

# Map Language Names to 2-letter ISO Codes for Whisper
LANG_CODES = {
    "English": "en",
    "German": "de",
    "Russian": "ru",
    "Arabic": "ar",
    "Urdu": "ur"
}


async def generate_tts(text_file, language, output_audio_path, voice_actor=None):
    # Select voice actor or fallback to language default
    if voice_actor in VOICE_ACTORS:
        voice = VOICE_ACTORS[voice_actor]
    else:
        voice = TTS_VOICES.get(language, TTS_VOICES["English"])

    print(f"   > 🎙️ Generating 1-Hour TTS Voiceover using voice: {voice}...")
    with open(text_file, 'r', encoding='utf-8') as f:
        script_text = f.read()
    
    chunks = [c.strip() for c in script_text.split('\n\n') if c.strip()]
    total = len(chunks)
    if not chunks:
        print("   > ⚠️ Script is empty. No TTS generated.")
        return False

    temp_files = []
    max_retries = 5

    print("\n" + "="*50)
    print("🎙️  ACTIVE TTS ENGINE: KOKORO (Local PyTorch) 🧠")
    print("="*50 + "\n")
    
    try:
        for i, chunk_text in enumerate(chunks):
            percent = int((i / total) * 100)
            bar_length = 20
            filled = int(bar_length * i / total)
            empty = bar_length - filled
            print(f"\r   > 🎙️ TTS Progress: [{'█' * filled}{'░' * empty}] {percent}% (Chunk {i+1}/{total})", end="", flush=True)
            
            chunk_file = os.path.join(TEMP_DIR, f"temp_chunk_{i}.wav")
            
            success = False
            for attempt in range(max_retries):
                try:
                    await asyncio.to_thread(sync_generate_kokoro, chunk_text, voice, chunk_file)
                    success = True
                    break
                except Exception as e:
                    print(f"\n   > ⚠️ Kokoro TTS Error on chunk {i+1} attempt {attempt + 1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        print("   > ⏳ Retrying in 2 seconds...")
                        await asyncio.sleep(2)
                    else:
                        print("   > ❌ Fatal: Kokoro TTS failed after maximum retries.")
                        raise e
            
            if success:
                temp_files.append(chunk_file)
            else:
                raise RuntimeError(f"Failed to generate TTS for chunk {i+1}")

        print(f"\r   > 🎙️ TTS Progress: [{'█' * bar_length}] 100% (Chunk {total}/{total})", flush=True)

        # Concatenate using ffmpeg concat demuxer
        print("   > 🔗 Concatenating TTS audio chunks...")
        list_file_path = os.path.join(TEMP_DIR, "list.txt")
        with open(list_file_path, "w", encoding="utf-8") as f:
            for tf in temp_files:
                abs_path = os.path.abspath(tf).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")

        ffmpeg_exe = FFMPEG_PATH
        cmd = [
            ffmpeg_exe,
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file_path,
            '-y', output_audio_path
        ]
        
        process = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        
        if process.returncode == 0:
            print("   > ✅ TTS generated and concatenated successfully.")
            return True
        else:
            print("   > ❌ FFmpeg Concatenation Failed.")
            return False
            
    finally:
        if 'list_file_path' in locals() and os.path.exists(list_file_path):
            try: os.remove(list_file_path)
            except: pass
        for tf in temp_files:
            if os.path.exists(tf):
                try: os.remove(tf)
                except: pass
