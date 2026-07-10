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

# Map Voice Actors to Kokoro Neural Voices (13 premium voices mapped for each language)
VOICE_ACTORS = {
    # English (US)
    "English (US) Bella (Premium Female)": "af_bella",
    "English (US) Sarah (Premium Female)": "af_sarah",
    "English (US) Nicole (Premium Female)": "af_nicole",
    "English (US) Sky (Premium Female)": "af_sky",
    "English (US) Heart (Premium Female)": "af_heart",
    "English (US) Adam (Premium Male)": "am_adam",
    "English (US) Michael (Premium Male)": "am_michael",
    "English (US) Fenrir (Premium Male)": "am_fenrir",
    "English (US) Puck (Premium Male)": "am_puck",
    
    # English (UK)
    "English (UK) Emma (Premium Female)": "bf_emma",
    "English (UK) Isabella (Premium Female)": "bf_isabella",
    "English (UK) George (Premium Male)": "bm_george",
    "English (UK) Lewis (Premium Male)": "bm_lewis",

    # German
    "German Bella (Premium Female)": "af_bella",
    "German Sarah (Premium Female)": "af_sarah",
    "German Nicole (Premium Female)": "af_nicole",
    "German Sky (Premium Female)": "af_sky",
    "German Heart (Premium Female)": "af_heart",
    "German Emma (Premium Female)": "bf_emma",
    "German Isabella (Premium Female)": "bf_isabella",
    "German Adam (Premium Male)": "am_adam",
    "German Michael (Premium Male)": "am_michael",
    "German George (Premium Male)": "bm_george",
    "German Lewis (Premium Male)": "bm_lewis",
    "German Fenrir (Premium Male)": "am_fenrir",
    "German Puck (Premium Male)": "am_puck",

    # Russian
    "Russian Bella (Premium Female)": "af_bella",
    "Russian Sarah (Premium Female)": "af_sarah",
    "Russian Nicole (Premium Female)": "af_nicole",
    "Russian Sky (Premium Female)": "af_sky",
    "Russian Heart (Premium Female)": "af_heart",
    "Russian Emma (Premium Female)": "bf_emma",
    "Russian Isabella (Premium Female)": "bf_isabella",
    "Russian Adam (Premium Male)": "am_adam",
    "Russian Michael (Premium Male)": "am_michael",
    "Russian George (Premium Male)": "bm_george",
    "Russian Lewis (Premium Male)": "bm_lewis",
    "Russian Fenrir (Premium Male)": "am_fenrir",
    "Russian Puck (Premium Male)": "am_puck",

    # Arabic
    "Arabic Bella (Premium Female)": "af_bella",
    "Arabic Sarah (Premium Female)": "af_sarah",
    "Arabic Nicole (Premium Female)": "af_nicole",
    "Arabic Sky (Premium Female)": "af_sky",
    "Arabic Heart (Premium Female)": "af_heart",
    "Arabic Emma (Premium Female)": "bf_emma",
    "Arabic Isabella (Premium Female)": "bf_isabella",
    "Arabic Adam (Premium Male)": "am_adam",
    "Arabic Michael (Premium Male)": "am_michael",
    "Arabic George (Premium Male)": "bm_george",
    "Arabic Lewis (Premium Male)": "bm_lewis",
    "Arabic Fenrir (Premium Male)": "am_fenrir",
    "Arabic Puck (Premium Male)": "am_puck",

    # Urdu
    "Urdu Bella (Premium Female)": "af_bella",
    "Urdu Sarah (Premium Female)": "af_sarah",
    "Urdu Nicole (Premium Female)": "af_nicole",
    "Urdu Sky (Premium Female)": "af_sky",
    "Urdu Heart (Premium Female)": "af_heart",
    "Urdu Emma (Premium Female)": "bf_emma",
    "Urdu Isabella (Premium Female)": "bf_isabella",
    "Urdu Adam (Premium Male)": "am_adam",
    "Urdu Michael (Premium Male)": "am_michael",
    "Urdu George (Premium Male)": "bm_george",
    "Urdu Lewis (Premium Male)": "bm_lewis",
    "Urdu Fenrir (Premium Male)": "am_fenrir",
    "Urdu Puck (Premium Male)": "am_puck"
}

# Map UI languages to defaults
TTS_VOICES = {
    "English": "af_bella",
    "Arabic": "af_bella",
    "German": "af_bella",
    "Russian": "af_bella",
    "Urdu": "af_bella"
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

    all_expected_files = [os.path.join(TEMP_DIR, f"temp_chunk_{i}.wav") for i in range(total)]

    print("\n" + "="*50)
    print("🎙️  ACTIVE TTS ENGINE: KOKORO (Local PyTorch) 🧠")
    print("="*50 + "\n")
    
    # Scale concurrency dynamically to utilize maximum system resources (up to 24 workers)
    logical_cores = psutil.cpu_count(logical=True) or 8
    concurrency_limit = max(8, min(logical_cores, 24))
    print(f"   > ⚡ Scaling TTS Concurrency Pool: {concurrency_limit} concurrent workers (Max resource usage)")

    sem = asyncio.Semaphore(concurrency_limit)
    completed_chunks = 0
    progress_lock = asyncio.Lock()
    max_retries = 5

    async def print_progress():
        async with progress_lock:
            percent = int((completed_chunks / total) * 100)
            bar_length = 20
            filled = int(bar_length * completed_chunks / total)
            empty = bar_length - filled
            print(f"\r   > 🎙️ TTS Progress: [{'█' * filled}{'░' * empty}] {percent}% ({completed_chunks}/{total})", end="", flush=True)

    async def generate_chunk_task(index, chunk_text):
        async with sem:
            chunk_file = all_expected_files[index]
            success = False
            for attempt in range(max_retries):
                try:
                    await asyncio.to_thread(sync_generate_kokoro, chunk_text, voice, chunk_file)
                    success = True
                    break
                except Exception as e:
                    print(f"\n   > ⚠️ Kokoro TTS Error on chunk {index+1} attempt {attempt + 1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        print("   > ❌ Fatal: Kokoro TTS failed after maximum retries.")
                        raise e
            if success:
                nonlocal completed_chunks
                completed_chunks += 1
                await print_progress()
                return index, chunk_file
            else:
                raise RuntimeError(f"Failed to generate TTS for chunk {index+1}")

    try:
        # Run all generation tasks concurrently
        tasks = [generate_chunk_task(i, chunk) for i, chunk in enumerate(chunks)]
        results = await asyncio.gather(*tasks)
        
        # Sort results by index to guarantee correct narrative order
        results.sort(key=lambda x: x[0])
        temp_files = [r[1] for r in results]

        print(f"\r   > 🎙️ TTS Progress: [{'█' * 20}] 100% ({total}/{total})", flush=True)

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
        for tf in all_expected_files:
            if os.path.exists(tf):
                try: os.remove(tf)
                except: pass
