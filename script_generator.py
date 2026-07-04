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

        print("========================================")
        print(f"✍️ INITIATING GROQ SCRIPT ENGINE (1-Hour Format)")
        print(f"🎬 Title: {title} | Lang: {language} | Style: {style}")
        print("========================================")

        IS_RUSSIAN_STORY = (style == "Russian Story (High Retention)")
        IS_FAMILY_DRAMA  = (style == "Family Drama (High Retention)")

        # ---------------------------------------------------------------
        # SYSTEM PROMPTS
        # ---------------------------------------------------------------
        if IS_RUSSIAN_STORY:
            # Part 1 — cold open, hook & twist enforced
            opening_system_prompt = (
                "You are an elite YouTube true-crime and drama scriptwriter. "
                "Your goal is maximum audience retention.\n"
                "CRITICAL RULES:\n"
                "1. No philosophical introductions. Start immediately with the action.\n"
                "2. 0:00 to 0:10 MUST be a punchy incident "
                '(e.g., "John kissed his wife goodbye. Three days later, police said he drowned.").\n'
                "3. 0:10 to 0:30 MUST contain a massive plot twist "
                '(e.g., "But five years later, his son saw him at the airport.").\n'
                "4. Write strictly at a 5th-grade reading level. "
                "Use short, sharp, factual sentences.\n"
                "5. BANNED WORDS: labyrinthine, tapestry, odyssey, depths of despair, "
                "human condition, abyss. Do not use flowery, poetic, or novel-like language.\n"
                "6. Focus on character actions, raw dialogue, and immediate conflict."
            )
            # Parts 2–N — zero recap, immediate continuation
            continuation_system_prompt = (
                "Continue the story from the exact second the last chapter ended. "
                "Maintain the fast-paced, zero-filler, short-sentence structure. "
                "DO NOT re-introduce the characters or summarize the previous chapter. "
                "Immediately output the next scene. "
                "BANNED WORDS: tapestry, odyssey, labyrinthine."
            )

        elif IS_FAMILY_DRAMA:
            # Part 1 — emotional hook, dialogue-driven conflict enforced
            opening_system_prompt = (
                "You are an elite YouTube scriptwriter specializing in viral Family Drama and relatable life stories. "
                "Your goal is maximum emotional engagement and viewer retention.\n"
                "CRITICAL RULES:\n"
                "1. No philosophical introductions or moralizing intros. "
                "Start immediately with the core family conflict.\n"
                "2. 0:00 to 0:15 MUST be a highly relatable but shocking hook "
                '(e.g., "For ten years, I treated my stepdaughter like my own. '
                'Then I saw the text messages on her phone.").\n'
                "3. Rely heavily on raw, realistic dialogue between family members to move the plot forward. "
                "Show, do not tell.\n"
                "4. Write at a 5th-grade reading level. Use conversational, everyday English.\n"
                "5. BANNED WORDS: tapestry, testament, symphony of emotions, rollercoaster of feelings, "
                "delve, navigate. Do not use poetic or melodramatic AI language.\n"
                "6. Build tension through secrets, betrayals, and satisfying resolutions."
            )
            # Parts 2–N — dialogue continuity, no recap
            continuation_system_prompt = (
                "Continue the family drama story from the exact sentence the last chapter ended. "
                "Maintain the heavy use of realistic dialogue and emotional tension. "
                "DO NOT summarize the previous chapter or re-introduce the family members. "
                "Immediately output the next scene. Keep the language conversational. "
                "BANNED WORDS: tapestry, navigate, symphony."
            )

        else:
            # Default system prompt for all other styles — unchanged
            system_prompt = (
                f"You are an elite, professional scriptwriter for a high-end, slow-paced YouTube documentary channel. "
                f"You write strictly in {language}. Your writing style is '{style}'. "
                f"CRITICAL RULES: "
                f"1. DO NOT SUMMARIZE. Write extremely long, detailed, and immersive paragraphs. "
                f"2. Take your time. Describe the atmosphere, historical context, and deep emotional stakes of every single moment. "
                f"3. Do not include visual cues, bracketed text, timestamps, or stage directions. Write ONLY the spoken voiceover dialogue. "
                f"4. You MUST output a massive wall of text. Aim for maximum length."
            )

        # ---------------------------------------------------------------
        # CONTEXT WINDOW — 500 words for high-retention styles, 100 for others
        # ---------------------------------------------------------------
        context_window = 500 if (IS_RUSSIAN_STORY or IS_FAMILY_DRAMA) else 100

        full_script = []
        last_paragraph = ""

        for part in range(1, total_parts + 1):
            print(f"   > ⏳ Generating Part {part}/{total_parts}...")

            # -----------------------------------------------------------
            # SELECT SYSTEM PROMPT FOR THIS PART
            # -----------------------------------------------------------
            if IS_RUSSIAN_STORY or IS_FAMILY_DRAMA:
                active_system = opening_system_prompt if part == 1 else continuation_system_prompt
            else:
                active_system = system_prompt

            # -----------------------------------------------------------
            # BUILD USER PROMPT
            # -----------------------------------------------------------
            if IS_RUSSIAN_STORY:
                if part == 1:
                    user_prompt = (
                        f"Write the cold open for a true-crime/drama video titled '{title}'.\n"
                        f"Hook: First 2 sentences must describe a shocking real-world incident involving a named person.\n"
                        f"Twist: Sentences 3–5 must deliver an immediate plot reversal that changes everything.\n"
                        f"Continue the scene with fast, factual dialogue and actions. No filler. No scene-setting monologues.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
                elif part == total_parts:
                    user_prompt = (
                        f"Here are the last {context_window} words of the previous chapter for continuity:\n"
                        f"\"{last_paragraph}\"\n\n"
                        f"Write the FINAL chapter. Resolve the story. Deliver the verdict, sentence, or outcome.\n"
                        f"End with exactly one sentence asking viewers to like and subscribe.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
                else:
                    user_prompt = (
                        f"Here are the last {context_window} words of the previous chapter for continuity:\n"
                        f"\"{last_paragraph}\"\n\n"
                        f"Continue IMMEDIATELY from this point. No recap. No re-introduction of characters.\n"
                        f"Write Chapter {part}: actions, raw dialogue, new conflict or revelation.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
            elif IS_FAMILY_DRAMA:
                if part == 1:
                    user_prompt = (
                        f"Write the emotional opening scene of a family drama story titled '{title}'.\n"
                        f"Hook: First 1-2 sentences must be a shocking, relatable revelation about a family relationship.\n"
                        f"Immediately launch into a tense family conversation using realistic dialogue.\n"
                        f"Introduce the key family members naturally through their words and actions — not through descriptions.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
                elif part == total_parts:
                    user_prompt = (
                        f"Here are the last {context_window} words of the previous chapter for continuity:\n"
                        f"\"{last_paragraph}\"\n\n"
                        f"Write the FINAL chapter of this family drama. Resolve the central conflict.\n"
                        f"Show the emotional resolution through dialogue and character reactions.\n"
                        f"End with one natural sentence inviting viewers to like and subscribe.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
                else:
                    user_prompt = (
                        f"Here are the last {context_window} words of the previous chapter for continuity:\n"
                        f"\"{last_paragraph}\"\n\n"
                        f"Continue IMMEDIATELY from this point. Do not recap or re-introduce family members.\n"
                        f"Write Chapter {part}: a new confrontation, secret revealed, or emotional turning point — through dialogue.\n"
                        f"Minimum 500 words. Output only the spoken script in {language}."
                    )
            else:
                # Original user prompts — unchanged for all other styles
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

            chunk_text = self._call_groq(active_system, user_prompt)

            if not chunk_text:
                print("   > 🛑 FATAL: Script generation failed mid-way. Halting to save API credits.")
                return None

            full_script.append(chunk_text)

            # Grab context words from the end of this chunk for the next part
            words = chunk_text.split()
            last_paragraph = " ".join(words[-context_window:]) if len(words) > context_window else chunk_text

            # Respect rate limits
            time.sleep(2)

        print("   > ✅ All parts generated successfully. Assembling master script...")
        master_script_text = "\n\n".join(full_script)

        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_')).rstrip()
        output_file = os.path.join(SCRIPT_DIR, f"{safe_title.replace(' ', '_')}.txt")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(master_script_text)

        print(f"   > 💾 Master Script saved locally to: {output_file}")
        return output_file


    def generate_youtube_metadata(self, script_text, language="English"):
        import json
        import re
        print(f"   > 🧠 Running AI metadata generator (Language: {language})...")

        system_prompt = (
            f"You are an expert YouTube SEO metadata generator. "
            f"Based on the provided video script, generate the following in {language}:\n\n"
            f"1. A highly clickable, engaging Title (under 70 characters).\n"
            f"2. A compelling Description structured in exactly 3 paragraphs:\n"
            f"   - Paragraph 1: A strong hook summarizing the mystery or core conflict of the video.\n"
            f"   - Paragraph 2: Additional context and intrigue without spoiling the ending.\n"
            f"   - Paragraph 3: A call to action (e.g. Like, Subscribe, leave a Comment).\n"
            f"3. Exactly 7 dynamic hashtags that perfectly match the specific genre, era, topic, "
            f"and subject matter of THIS script. Do NOT use generic fallback tags like #Documentary or #History. "
            f"Extract hashtags from the actual script content (characters, events, locations, themes).\n\n"
            f"LANGUAGE RULE: Write the title, all 3 description paragraphs, and all hashtags entirely in {language}.\n\n"
            f"Format your response strictly as a JSON object with exactly these three keys:\n"
            f"{{\n"
            f'  "title": "...",\n'
            f'  "description": "paragraph1\\n\\nparagraph2\\n\\nparagraph3",\n'
            f'  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#tag6", "#tag7"]\n'
            f"}}\n\n"
            f"CRITICAL: Output ONLY valid JSON. No markdown, no code fences, no extra text."
        )

        # Trim script to fit token limits (first 3000 words + last 1000 words)
        words = script_text.split()
        if len(words) > 4000:
            prompt_text = " ".join(words[:3000]) + "\n... [Script truncated] ...\n" + " ".join(words[-1000:])
        else:
            prompt_text = script_text

        user_prompt = (
            f"Video Script:\n{prompt_text}\n\n"
            f"Output ONLY the raw JSON object with title, description (3 paragraphs), "
            f"and 7 dynamic hashtags — all written in {language}."
        )

        response = self._call_groq(system_prompt, user_prompt)
        if not response:
            print("   > ⚠️ Warning: Failed to generate dynamic metadata. Using fallback.")
            return None

        try:
            # Strip markdown fences if Groq wraps the response
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            data = json.loads(cleaned)

            title = data.get("title", "").strip()
            description = data.get("description", "").strip()
            hashtags = data.get("hashtags", [])

            if not title or not description:
                print("   > ⚠️ Warning: JSON missing 'title' or 'description' keys.")
                return None

            # Sanitize hashtags: ensure each starts with #, strip whitespace
            clean_tags = []
            for tag in hashtags:
                tag = str(tag).strip()
                if not tag.startswith("#"):
                    tag = "#" + tag
                clean_tags.append(tag)

            # Append hashtags to bottom of description for YouTube body text
            if clean_tags:
                hashtag_line = " ".join(clean_tags)
                full_description = f"{description}\n\n{hashtag_line}"
            else:
                full_description = description

            # Strip bare tag strings (e.g. "#tag") from the tags list to pass as
            # YouTube API search tags (without the # prefix)
            api_tags = [t.lstrip("#") for t in clean_tags]

            print(f"   > ✅ AI Metadata generated in {language} | Tags: {', '.join(clean_tags)}")
            return {
                "title": title,
                "description": full_description,
                "tags": api_tags
            }

        except Exception as e:
            print(f"   > ⚠️ Warning: Failed to parse metadata JSON: {e}. Raw response: {response}")
            # Regex fallback — recover title and description at minimum
            try:
                title_match = re.search(r'"title"\s*:\s*"([^"]+)"', response)
                desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', response)
                if title_match and desc_match:
                    return {
                        "title": title_match.group(1),
                        "description": desc_match.group(1).replace(r'\n', '\n'),
                        "tags": []
                    }
            except Exception:
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
