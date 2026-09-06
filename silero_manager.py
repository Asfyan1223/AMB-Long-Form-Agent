import os
import sys
import re
import threading

# Force Windows terminal to support UTF-8 emojis without crashing
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try: sys.stderr.reconfigure(encoding='utf-8')
    except Exception: pass

import torch
import numpy as np
import soundfile as sf

# Thread safety lock for Silero model inference
_silero_lock = threading.Lock()

class SileroTTSManager:
    """
    Dedicated Silero Neural TTS Manager.
    Initializes models via PyTorch Hub and synthesizes 48000 Hz audio directly
    to disk via soundfile, completely bypassing torchaudio.save().
    """
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SileroTTSManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, language='ru', speaker_model='v4_ru', default_speaker='xenia', sample_rate=48000, device=None):
        if self._initialized:
            return
            
        self.language = language
        self.speaker_model = speaker_model
        self.default_speaker = default_speaker
        self.sample_rate = sample_rate

        # Ensure model defaults to CPU unless CUDA device is explicitly detected
        if device is not None:
            self.device = torch.device(device)
        elif torch.cuda.is_available():
            self.device = torch.device('cuda')
        else:
            self.device = torch.device('cpu')

        print(f"   > 🎙️ Initializing Silero TTS Engine [Language: {self.language} | Model: {self.speaker_model} | Device: {self.device}]...")

        with _silero_lock:
            self.model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-models',
                model='silero_tts',
                language=self.language,
                speaker=self.speaker_model,
                trust_repo=True
            )
            self.model.to(self.device)

        print("   > 🚀 Silero TTS Model Loaded Successfully into Memory.")
        self._initialized = True

    def apply_tts(self, text: str, speaker: str = None, sample_rate: int = None) -> np.ndarray:
        """
        Runs model.apply_tts() and converts PyTorch tensor to a NumPy array.
        CRITICAL: Never uses torchaudio.save().
        """
        speaker = speaker or self.default_speaker
        sample_rate = sample_rate or self.sample_rate

        clean_text = text.strip()
        if not clean_text:
            return np.zeros(0, dtype=np.float32)

        with _silero_lock:
            with torch.inference_mode():
                audio_tensor = self.model.apply_tts(
                    text=clean_text,
                    speaker=speaker,
                    sample_rate=sample_rate
                )
                
                # Convert resulting PyTorch tensor to NumPy array
                audio_np = audio_tensor.cpu().numpy()
                return audio_np

    def generate(self, text: str, output_path: str, speaker: str = None, sample_rate: int = None) -> str:
        """
        Generates audio for a single text chunk and saves directly to disk via soundfile.write().
        """
        sample_rate = sample_rate or self.sample_rate
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        audio_np = self.apply_tts(text, speaker=speaker, sample_rate=sample_rate)
        if len(audio_np) == 0:
            audio_np = np.zeros(int(sample_rate * 0.5), dtype=np.float32)
            
        sf.write(output_path, audio_np, sample_rate)
        return output_path

    def split_script_into_chunks(self, text: str, max_chunk_words: int = 40) -> list:
        """
        Splits script text into sentence/phrase chunks suited for Silero inference.
        Prevents model memory overflow and token limit drops.
        """
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        chunks = []

        for p in paragraphs:
            # Split by punctuation (period, exclamation, question mark, colon, semicolon)
            sentences = re.split(r'(?<=[.!?։؛\n])\s+', p)
            curr = []
            curr_len = 0
            
            for s in sentences:
                s_strip = s.strip()
                if not s_strip:
                    continue
                w_count = len(s_strip.split())
                if curr_len + w_count > max_chunk_words and curr:
                    chunks.append(" ".join(curr))
                    curr = [s_strip]
                    curr_len = w_count
                else:
                    curr.append(s_strip)
                    curr_len += w_count
                    
            if curr:
                chunks.append(" ".join(curr))

        return chunks if chunks else ([text.strip()] if text.strip() else [])

    def generate_from_script(self, script_path_or_text: str, output_path: str, speaker: str = None, sample_rate: int = None, progress_callback=None) -> bool:
        """
        Reads a full script, chunks it, applies Silero TTS across chunks, concatenates
        NumPy arrays, and writes a pristine 48000 Hz .wav file via soundfile.
        """
        sample_rate = sample_rate or self.sample_rate
        speaker = speaker or self.default_speaker

        if os.path.exists(script_path_or_text):
            with open(script_path_or_text, 'r', encoding='utf-8') as f:
                script_text = f.read()
        else:
            script_text = script_path_or_text

        chunks = self.split_script_into_chunks(script_text)
        total_chunks = len(chunks)
        if total_chunks == 0:
            print("   > ⚠️ Warning: Empty script provided for Silero TTS.")
            return False

        print(f"\n==================================================")
        print(f"🎙️  ACTIVE TTS ENGINE: SILERO NEURAL TTS ({self.device.type.upper()}) ⚡")
        print(f"🗣️  Speaker: '{speaker}' | Sample Rate: {sample_rate} Hz | Chunks: {total_chunks}")
        print(f"==================================================\n")

        audio_arrays = []
        silence_gap = np.zeros(int(sample_rate * 0.15), dtype=np.float32) # 150ms natural pause between sentences

        for idx, chunk in enumerate(chunks, 1):
            try:
                chunk_audio = self.apply_tts(chunk, speaker=speaker, sample_rate=sample_rate)
                if len(chunk_audio) > 0:
                    audio_arrays.append(chunk_audio)
                    audio_arrays.append(silence_gap)
            except Exception as e:
                print(f"   > ⚠️ Silero chunk #{idx} warning: {e}. Skipping chunk.")

            pct = int((idx / total_chunks) * 100)
            filled = int(15 * pct / 100)
            empty = 15 - filled
            sys.stdout.write(f"\r[+] 🎙️ Silero TTS Progress: [{'█' * filled}{'░' * empty}] {pct}% ({idx}/{total_chunks} Chunks Done)")
            sys.stdout.flush()

            if progress_callback:
                progress_callback(pct, f"Silero TTS ({idx}/{total_chunks})")

        sys.stdout.write("\n")
        sys.stdout.flush()

        if not audio_arrays:
            print("   > ❌ Fatal: No audio data generated by Silero TTS.")
            return False

        combined_audio = np.concatenate(audio_arrays)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        # Save directly using soundfile.write() - bypassing torchaudio.save()
        sf.write(output_path, combined_audio, sample_rate)
        
        duration_sec = round(len(combined_audio) / sample_rate, 2)
        print(f"   > ✅ Master Audio Track Synthesized ({duration_sec}s @ {sample_rate}Hz) -> {output_path}")
        return True


# Global default manager instance
_default_manager = None

def get_silero_manager(language='ru', speaker_model='v4_ru', default_speaker='xenia', sample_rate=48000) -> SileroTTSManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SileroTTSManager(
            language=language,
            speaker_model=speaker_model,
            default_speaker=default_speaker,
            sample_rate=sample_rate
        )
    return _default_manager

def sync_generate_silero(text: str, speaker: str = 'xenia', output_path: str = None, sample_rate: int = 48000) -> str:
    """
    Synchronous one-shot audio generation helper.
    """
    mgr = get_silero_manager(sample_rate=sample_rate)
    return mgr.generate(text, output_path=output_path, speaker=speaker, sample_rate=sample_rate)

async def generate_tts(text_file: str, language: str, output_audio_path: str, voice_actor: str = None, progress_callback=None) -> bool:
    """
    Async interface matching the signature used by video rendering pipeline.
    """
    mgr = get_silero_manager(sample_rate=48000)
    speaker = voice_actor if (voice_actor and voice_actor in ['aidar', 'baya', 'kseniya', 'xenia', 'eugene']) else 'xenia'
    return mgr.generate_from_script(
        script_path_or_text=text_file,
        output_path=output_audio_path,
        speaker=speaker,
        sample_rate=48000,
        progress_callback=progress_callback
    )
