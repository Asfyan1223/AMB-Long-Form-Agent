import os
import time
from groq import Groq

# Create a folder to save our long scripts safely
SCRIPT_DIR = "lf_scripts"
os.makedirs(SCRIPT_DIR, exist_ok=True)

# Class orchestrates long-form scripting. Checkpointing/Smart Resume bypasses this 
# generation step if the title-sanitized script file already exists in lf_scripts.
class LongFormScripter:
    def __init__(self, api_keys_input, custom_length_enabled=False, target_minutes=60):
        import os
        import math
        from groq import Groq
        
        # Parse the comma-separated string or list into a clean array
        if isinstance(api_keys_input, str):
            self.api_keys = [k.strip() for k in api_keys_input.split(",") if k.strip()]
        elif isinstance(api_keys_input, list):
            self.api_keys = [k.strip() for k in api_keys_input if k.strip()]
        else:
            self.api_keys = []
            
        self.current_key_index = 0
        self.model = "llama-3.3-70b-versatile"
        
        if self.api_keys:
            self.client = Groq(api_key=self.api_keys[self.current_key_index])
        else:
            self.client = None

        if custom_length_enabled:
            target_words = target_minutes * 150  # Average TTS reading speed is 150 WPM
            # An average single AI generation part yields ~1500 words
            self.total_parts = math.ceil(target_words / 1500)
        else:
            self.total_parts = 6 # Default 1-hour generation fallback (6 parts * ~1500 words = ~9000 words)

    def switch_key(self):
        from groq import Groq
        self.current_key_index += 1
        if self.current_key_index < len(self.api_keys):
            print(f"   > 🔄 Rate limit hit. Switching to Backup Groq API Key (Slot {self.current_key_index + 1})...")
            self.client = Groq(api_key=self.api_keys[self.current_key_index])
            return True
        return False

    def _call_groq(self, system_prompt, user_prompt, retries=5):
        import re
        import time
        for attempt in range(retries):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2500,
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "Rate limit" in error_str:
                    if self.switch_key():
                        continue # Instantly retry the API call with the new key
                    
                    # If switch_key() returns False, all keys are exhausted. Trigger auto-pause.
                    print(f"   > ⚠️ ALL Groq keys exhausted. Initiating cooldown...")
                    match = re.search(r"try again in(?: (\d+)h)?(?: (\d+)m)?(?: ([\d\.]+)s)?", error_str)
                    if match:
                        hrs = int(match.group(1)) if match.group(1) else 0
                        mins = int(match.group(2)) if match.group(2) else 0
                        secs = float(match.group(3)) if match.group(3) else 0.0
                        wait_time = int((hrs * 3600) + (mins * 60) + secs + 5)
                        print(f"   > ⏳ Auto-pausing background thread for {wait_time/60:.1f} minutes. Do not close the app...")
                        
                        import sys
                        for remaining in range(wait_time, 0, -1):
                            r_mins = remaining // 60
                            r_secs = remaining % 60
                            sys.stdout.write(f"\r   > ⏳ Auto-pausing background thread: {r_mins:02d}m {r_secs:02d}s remaining... ")
                            sys.stdout.flush()
                            time.sleep(1)
                        print("\n   > 🔄 Resuming Groq part generation...")
                        
                        if self.api_keys:
                            # Reset index to 0 after global pause, assuming keys have reset
                            self.current_key_index = 0
                            from groq import Groq
                            self.client = Groq(api_key=self.api_keys[self.current_key_index])
                        continue
                    else:
                        print("   > ⏳ Unparsed rate limit. Defaulting to 60-second pause...")
                        import sys
                        for remaining in range(60, 0, -1):
                            sys.stdout.write(f"\r   > ⏳ Auto-pausing background thread: {remaining}s remaining... ")
                            sys.stdout.flush()
                            time.sleep(1)
                        print("\n   > 🔄 Resuming Groq part generation...")
                        
                        if self.api_keys:
                            # Reset index to 0 after global pause, assuming keys have reset
                            self.current_key_index = 0
                            from groq import Groq
                            self.client = Groq(api_key=self.api_keys[self.current_key_index])
                        continue
                else:
                    print(f"   > ❌ Groq API Error: {e}")
                    return None
                    
        print("   > 🛑 FATAL: Max retries exceeded.")
        return None

    def generate_full_script(self, title, language="English", style="Deep Emotional", total_parts=None):
        if total_parts is None:
            total_parts = self.total_parts
        # Increased default total_parts to 20. 20 parts * ~450 words = ~9,000 words (1 hour)
        print("========================================")
        print(f"✍️ INITIATING GROQ SCRIPT ENGINE (1-Hour Format)")
        print(f"🎬 Title: {title} | Lang: {language} | Style: {style}")
        print("========================================")

        # Aggressive System Prompt
        system_prompt = (
            f"You are an elite, professional scriptwriter for a high-end, slow-paced YouTube documentary channel. "
            f"You write strictly in {language}. Your writing style is '{style}'. "
            f"CRITICAL RULES: "
            f"1. DO NOT SUMMARIZE. Write extremely long, detailed, and immersive paragraphs. "
            f"2. Take your time. Describe the atmosphere, historical context, and deep emotional stakes of every single moment. "
            f"3. Do not include visual cues, bracketed text, timestamps, or stage directions. Write ONLY the spoken voiceover dialogue. "
            f"4. You MUST output a massive wall of text. Aim for maximum length."
        )

        full_script = []
        last_paragraph = ""

        for part in range(1, total_parts + 1):
            print(f"   > ⏳ Generating Part {part}/{total_parts} (Targeting heavy detail)...")
            
            if part == 1:
                user_prompt = (
                    f"Write the powerful, slow-building introduction and Part 1 of a 1-hour deep-dive video titled '{title}'. "
                    f"Hook the viewer immediately, but do not rush the story. Paint a vivid picture of the world and the stakes. "
                    f"Write a minimum of 600 words. Output only the spoken script in {language}."
                )
            elif part == total_parts:
                user_prompt = (
                    f"We are writing a video titled '{title}'. "
                    f"Here is the end of the previous section to maintain flow:\n\"{last_paragraph}\"\n\n"
                    f"Now, write the final Part {total_parts}. This is the grand conclusion. "
                    f"Summarize the overarching lessons and wrap up the narrative powerfully. Include a subtle call to action to subscribe. "
                    f"Write a minimum of 500 words. Output only the spoken script in {language}."
                )
            else:
                user_prompt = (
                    f"We are writing a 1-hour video titled '{title}'. "
                    f"Here is the end of the previous section to maintain flow:\n\"{last_paragraph}\"\n\n"
                    f"Continue the narrative seamlessly from exactly where that left off. Write Part {part}. "
                    f"CRITICAL: Do NOT skip ahead. Expand heavily on the current scene or topic. "
                    f"Dive deep into the philosophy, mechanics, or history of this specific moment. "
                    f"Write a minimum of 600 words. Output only the spoken script in {language}."
                )

            chunk_text = self._call_groq(system_prompt, user_prompt)
            
            if not chunk_text:
                print("   > 🛑 FATAL: Script generation failed mid-way. Halting to save API credits.")
                return None

            full_script.append(chunk_text)
            
            # Grab the last 100 words to feed into the next prompt for rock-solid continuity
            words = chunk_text.split()
            last_paragraph = " ".join(words[-100:]) if len(words) > 100 else chunk_text

            # Sleep to respect rate limits and let the buffer breathe
            time.sleep(2)

        print("   > ✅ All parts generated successfully. Assembling master script...")
        master_script_text = "\n\n".join(full_script)
        
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_')).rstrip()
        output_file = os.path.join(SCRIPT_DIR, f"{safe_title.replace(' ', '_')}.txt")
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(master_script_text)
            
        print(f"   > 💾 Master Script saved locally to: {output_file}")
        return output_file

    def generate_youtube_metadata(self, script_text):
        import json
        import re
        print("   > 🧠 Running AI metadata generator...")
        system_prompt = (
            "You are an SEO expert. Read this video script and output a JSON object containing two keys: "
            "'title' (a highly engaging, click-worthy YouTube title under 70 characters) and "
            "'description' (a punchy, SEO-optimized summary with 5 relevant hashtags). "
            "CRITICAL: Output ONLY valid JSON. Do not include markdown code block formatting (like ```json), introduction, or conclusion."
        )
        
        # Take a subset of the script text if it is too long to fit in standard token limits (e.g. first 3000 words + last 1000 words)
        words = script_text.split()
        if len(words) > 4000:
            prompt_text = " ".join(words[:3000]) + "\n... [Script truncated for brevity] ...\n" + " ".join(words[-1000:])
        else:
            prompt_text = script_text
            
        user_prompt = f"Video Script:\n{prompt_text}\n\nOutput ONLY raw JSON format."
        
        response = self._call_groq(system_prompt, user_prompt)
        if not response:
            print("   > ⚠️ Warning: Failed to generate dynamic metadata. Using fallback.")
            return None
            
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            
            data = json.loads(cleaned)
            if "title" in data and "description" in data:
                return data
            else:
                print("   > ⚠️ Warning: JSON did not contain 'title' and 'description' keys.")
                return None
        except Exception as e:
            print(f"   > ⚠️ Warning: Failed to parse metadata JSON: {e}. Raw response: {response}")
            try:
                title_match = re.search(r'"title"\s*:\s*"([^"]+)"', response)
                desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', response)
                if title_match and desc_match:
                    return {
                        "title": title_match.group(1),
                        "description": desc_match.group(1).replace(r'\n', '\n')
                    }
            except:
                pass
            return None

# --- STANDALONE TESTER ---
if __name__ == "__main__":
    import json
    
    # Grab the Groq API key from settings.json for a quick test
    test_key = None
    if os.path.exists("settings.json"):
        with open("settings.json", "r") as f:
            settings = json.load(f)
            for profile in settings.values():
                if profile.get("groq_api_key") and "YOUR_" not in profile.get("groq_api_key"):
                    test_key = profile.get("groq_api_key")
                    break
                    
    if test_key:
        scripter = LongFormScripter(test_key)
        # We will test with just 3 parts to save time right now
        result = scripter.generate_full_script("The Hidden History of the Abbasid Caliphate", total_parts=3)
    else:
        print("❌ Please add your Groq API Key to the Agency Settings GUI first!")
