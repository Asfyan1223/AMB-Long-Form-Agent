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

SILERO_MODELS = {
    'en': {'model': 'silero_tts', 'speaker': 'v3_en', 'default_speaker': 'en_0'},
    'ru': {'model': 'silero_tts', 'speaker': 'v4_ru', 'default_speaker': 'xenia'},
    'de': {'model': 'silero_tts', 'speaker': 'v3_de', 'default_speaker': 'eva_k'},
    'es': {'model': 'silero_tts', 'speaker': 'v3_es', 'default_speaker': 'es_0'},
    'fr': {'model': 'silero_tts', 'speaker': 'v3_fr', 'default_speaker': 'fr_0'},
    'indic': {'model': 'silero_tts', 'speaker': 'v3_indic', 'default_speaker': 'hindi'}
}

EN_SPEAKER_MAP = {
    'xenia': 'en_0',
    'baya': 'en_21',
    'kseniya': 'en_0',
    'aidar': 'en_1',
    'eugene': 'en_2'
}

RU_SPEAKER_MAP = {
    'en_0': 'xenia',
    'en_1': 'aidar',
    'en_2': 'eugene'
}

def detect_language(text: str, default: str = 'en') -> str:
    """Accurately detects whether text is Russian (Cyrillic), Urdu/Arabic, or English (Latin)."""
    if not text:
        return default
    if re.search(r'[\u0400-\u04FF]', text):
        return 'ru'
    if re.search(r'[\u0600-\u06FF\u0750-\u077F]', text):
        return 'indic'
    return 'en'

class SileroTTSManager:
    """
    Dedicated Multi-Language Silero Neural TTS Manager.
    Dynamically loads and caches language models (English v3_en, Russian v4_ru, etc.)
    and synthesizes pristine 48000 Hz audio directly to disk via soundfile.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SileroTTSManager, cls).__new__(cls)
            cls._instance.models = {}
            cls._instance.sample_rate = 48000
            if torch.cuda.is_available():
                cls._instance.device = torch.device('cuda')
            else:
                cls._instance.device = torch.device('cpu')
        return cls._instance

    def get_model(self, lang_code: str):
        """Loads and caches the model for the requested language."""
        lang_key = lang_code.lower().strip() if lang_code else 'en'
        if lang_key in ['russian', 'ru']:
            target_lang = 'ru'
        elif lang_key in ['german', 'de']:
            target_lang = 'de'
        elif lang_key in ['spanish', 'es']:
            target_lang = 'es'
        elif lang_key in ['french', 'fr']:
            target_lang = 'fr'
        elif lang_key in ['hindi', 'urdu', 'indic']:
            target_lang = 'indic'
        else:
            target_lang = 'en'

        info = SILERO_MODELS.get(target_lang, SILERO_MODELS['en'])
        speaker_model = info['speaker']

        with _silero_lock:
            if target_lang not in self.models:
                print(f"   > 🎙️ Initializing Silero TTS Engine [Language: {target_lang} | Model: {speaker_model} | Device: {self.device}]...")
                local_hub = os.path.join(torch.hub.get_dir(), 'snakers4_silero-models_master')
                source_arg = 'local' if os.path.exists(local_hub) else 'github'
                repo_arg = local_hub if os.path.exists(local_hub) else 'snakers4/silero-models'
                model, _ = torch.hub.load(
                    repo_or_dir=repo_arg,
                    model='silero_tts',
                    language=target_lang,
                    speaker=speaker_model,
                    source=source_arg,
                    trust_repo=True
                )
                model.to(self.device)
                self.models[target_lang] = model
                print(f"   > 🚀 Silero [{target_lang.upper()} - {speaker_model}] Loaded Successfully into Memory.")
            return self.models[target_lang], target_lang, info['default_speaker']

    def preload_models(self, languages=['ru', 'en']):
        """Preloads specified models into memory for instantaneous inference."""
        for lang in languages:
            try:
                self.get_model(lang)
            except Exception as e:
                print(f"   > ⚠️ Silero preload error ({lang}): {e}")

    def resolve_speaker(self, speaker: str, lang_code: str, default_spk: str) -> str:
        if not speaker:
            return default_spk
        spk_lower = str(speaker).lower().strip()

        if lang_code == 'en':
            if spk_lower in EN_SPEAKER_MAP:
                return EN_SPEAKER_MAP[spk_lower]
            if spk_lower.startswith('en_'):
                return spk_lower
            if any(k in spk_lower for k in ['male', 'deep', 'adam', 'michael', 'george', 'aidar', 'eugene']):
                return 'en_1'
            return 'en_0'

        elif lang_code == 'ru':
            if spk_lower in ['aidar', 'baya', 'kseniya', 'xenia', 'eugene']:
                return spk_lower
            if spk_lower in RU_SPEAKER_MAP:
                return RU_SPEAKER_MAP[spk_lower]
            if any(k in spk_lower for k in ['male', 'deep']):
                return 'aidar'
            return 'xenia'

        return default_spk

    def apply_tts(self, text: str, speaker: str = None, sample_rate: int = 48000, language: str = None) -> np.ndarray:
        """
        Runs model.apply_tts() and converts PyTorch tensor to a NumPy array.
        """
        clean_text = text.strip()
        if not clean_text:
            return np.zeros(0, dtype=np.float32)

        if not language:
            lang_code = detect_language(clean_text)
        else:
            lang_code = 'ru' if language.lower() in ['ru', 'russian'] else ('en' if language.lower() in ['en', 'english'] else detect_language(clean_text))

        if lang_code == 'ru' and not re.search(r'[\u0400-\u04FF]', clean_text) and re.search(r'[a-zA-Z]', clean_text):
            lang_code = 'en'

        model, actual_lang, default_spk = self.get_model(lang_code)
        valid_speaker = self.resolve_speaker(speaker, actual_lang, default_spk)

        with _silero_lock:
            with torch.inference_mode():
                audio_tensor = model.apply_tts(
                    text=clean_text,
                    speaker=valid_speaker,
                    sample_rate=sample_rate
                )
                if audio_tensor is not None and audio_tensor.numel() > 0:
                    return audio_tensor.cpu().numpy().astype(np.float32)
                return np.zeros(0, dtype=np.float32)

    def generate(self, text: str, output_path: str, speaker: str = None, sample_rate: int = 48000, language: str = None) -> str:
        sample_rate = sample_rate or self.sample_rate
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        audio_np = self.apply_tts(text, speaker=speaker, sample_rate=sample_rate, language=language)
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

    def generate_from_script(self, script_path_or_text: str, output_path: str, speaker: str = None, sample_rate: int = 48000, language: str = None, progress_callback=None) -> bool:
        if os.path.exists(script_path_or_text):
            with open(script_path_or_text, 'r', encoding='utf-8', errors='ignore') as f:
                script_text = f.read()
        else:
            script_text = script_path_or_text

        chunks = self.split_script_into_chunks(script_text)
        total_chunks = len(chunks)
        if total_chunks == 0:
            print("   > ⚠️ Warning: Empty script provided for Silero TTS.")
            return False

        # Detect language of the script
        detected_lang = detect_language(script_text, default=language or 'en')
        if language and language.lower() in ['ru', 'russian'] and not re.search(r'[\u0400-\u04FF]', script_text):
            print(f"   > 💡 Note: Profile language is set to Russian, but script text is in English.")
            print(f"   > 🌐 Auto-switching Silero model to English (v3_en) so all chunks synthesize properly!")
            detected_lang = 'en'
        elif language and language.lower() in ['en', 'english'] and re.search(r'[\u0400-\u04FF]', script_text):
            print(f"   > 💡 Note: Profile language is set to English, but script text contains Cyrillic (Russian).")
            print(f"   > 🌐 Auto-switching Silero model to Russian (v4_ru)!")
            detected_lang = 'ru'

        model, actual_lang, default_spk = self.get_model(detected_lang)
        active_speaker = self.resolve_speaker(speaker, actual_lang, default_spk)

        print(f"\n==================================================")
        print(f"🎙️  ACTIVE TTS ENGINE: SILERO NEURAL TTS ({self.device.type.upper()}) ⚡")
        print(f"🗣️  Language: {actual_lang.upper()} | Speaker: '{active_speaker}' | Sample Rate: {sample_rate} Hz | Chunks: {total_chunks}")
        print(f"==================================================\n")

        audio_arrays = []
        silence_gap = np.zeros(int(sample_rate * 0.15), dtype=np.float32)

        failed_chunks = 0
        for idx, chunk in enumerate(chunks, 1):
            try:
                chunk_audio = self.apply_tts(chunk, speaker=active_speaker, sample_rate=sample_rate, language=actual_lang)
                if len(chunk_audio) > 0:
                    audio_arrays.append(chunk_audio)
                    audio_arrays.append(silence_gap)
                else:
                    failed_chunks += 1
            except Exception as e:
                failed_chunks += 1
                print(f"   > ⚠️ Silero chunk #{idx} warning: {type(e).__name__} ({e}). Skipping chunk.")

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
            print(f"   > ❌ Fatal: No audio data generated by Silero TTS ({failed_chunks}/{total_chunks} chunks failed).")
            return False

        combined_audio = np.concatenate(audio_arrays)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        sf.write(output_path, combined_audio, sample_rate)

        duration_sec = round(len(combined_audio) / sample_rate, 2)
        dur_m, dur_s = int(duration_sec // 60), int(duration_sec % 60)
        print(f"   > ✅ Master Audio Track Synthesized ({dur_m:02d}:{dur_s:02d} | {duration_sec}s @ {sample_rate}Hz) -> {output_path}")
        return True

_default_manager = None

def get_silero_manager(language=None, sample_rate=48000) -> SileroTTSManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SileroTTSManager()
    if language:
        _default_manager.get_model(language)
    return _default_manager

def sync_generate_silero(text: str, speaker: str = None, output_path: str = None, sample_rate: int = 48000, language: str = None) -> str:
    mgr = get_silero_manager()
    return mgr.generate(text, output_path=output_path, speaker=speaker, sample_rate=sample_rate, language=language)

async def generate_tts(text_file: str, language: str, output_audio_path: str, voice_actor: str = None, progress_callback=None) -> bool:
    mgr = get_silero_manager()
    return mgr.generate_from_script(
        script_path_or_text=text_file,
        output_path=output_audio_path,
        speaker=voice_actor,
        sample_rate=48000,
        language=language,
        progress_callback=progress_callback
    )
