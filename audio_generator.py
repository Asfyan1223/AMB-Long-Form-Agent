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

TEMP_DIR = os.path.join(os.getcwd(), "lf_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Map Voice Actors to edge_tts Neural Voices
VOICE_ACTORS = {
    "English (US) Male": "en-US-ChristopherNeural",
    "English (US) Female": "en-US-EmmaNeural",
    "English (UK) Male": "en-GB-RyanNeural",
    "English (UK) Female": "en-GB-SoniaNeural",
    "German Male": "de-DE-KillianNeural",
    "German Female": "de-DE-KatjaNeural",
    "Russian Male": "ru-RU-DmitryNeural",
    "Russian Female": "ru-RU-SvetlanaNeural",
    "Arabic Male": "ar-AE-HamdanNeural",
    "Arabic Female": "ar-AE-FatimaNeural",
    "Urdu Male": "ur-PK-AsadNeural",
    "Urdu Female": "ur-PK-UzmaNeural"
}

# Map UI languages to Edge TTS Voices (defaults)
TTS_VOICES = {
    "English": "en-US-ChristopherNeural",
    "Arabic": "ar-AE-HamdanNeural",
    "German": "de-DE-KillianNeural",
    "Russian": "ru-RU-DmitryNeural",
    "Urdu": "ur-PK-AsadNeural"
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
    
    try:
        for i, chunk_text in enumerate(chunks):
            percent = int((i / total) * 100)
            bar_length = 20
            filled = int(bar_length * i / total)
            empty = bar_length - filled
            print(f"\r   > 🎙️ TTS Progress: [{'█' * filled}{'░' * empty}] {percent}% (Chunk {i+1}/{total})", end="", flush=True)
            
            chunk_file = os.path.join(TEMP_DIR, f"temp_chunk_{i}.mp3")
            
            success = False
            for attempt in range(max_retries):
                try:
                    communicate = edge_tts.Communicate(chunk_text, voice)
                    await communicate.save(chunk_file)
                    success = True
                    break
                except Exception as e:
                    print(f"\n   > ⚠️ Edge TTS Connection Error on chunk {i+1} attempt {attempt + 1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        print("   > ⏳ Retrying connection in 10 seconds...")
                        await asyncio.sleep(10)
                    else:
                        print("   > ❌ Fatal: Edge TTS failed after maximum retries.")
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
            '-c', 'copy',
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
