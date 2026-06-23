import discord
import json
import os

import sys
import io

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        except Exception:
            pass

if getattr(sys, 'frozen', False):
    install_dir = os.path.dirname(sys.executable)
else:
    install_dir = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(os.environ.get('APPDATA', ''), 'IslamicReelsStudio', 'settings.json')
QUEUE_DIR = os.path.join(install_dir, "lf_queues")
ASSETS_DIR = os.path.join(install_dir, "lf_assets")

# Create directories for long-form assets and queues
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

class AMBMasterAgent(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.channel_to_profile = {}
        self.load_settings()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                for profile_name, config in settings.items():
                    channel_id = config.get("discord_channel_id", "")
                    if channel_id and channel_id.strip() and "YOUR_" not in channel_id:
                        self.channel_to_profile[int(channel_id)] = profile_name

    async def on_ready(self):
        print("========================================")
        print(f"🤖 AMB Master Agent Logged In: {self.user}")
        print(f"📡 Active Channels Mapped: {list(self.channel_to_profile.values())}")
        print("========================================")

    async def on_message(self, message):
        # Ignore messages sent by the bot itself
        if message.author == self.user:
            return

        # Check if the message is in one of our assigned profile channels
        profile_name = self.channel_to_profile.get(message.channel.id)
        if not profile_name:
            return

        # Require an image attachment
        if not message.attachments:
            await message.channel.send("⚠️ **Error:** Please attach a thumbnail image with your video title.")
            return

        # Require a text prompt (the video title)
        title = message.content.strip()
        if not title:
            await message.channel.send("⚠️ **Error:** Please write a video title in the image caption.")
            return

        attachment = message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await message.channel.send("⚠️ **Error:** The attached file must be an image.")
            return

        # Download the thumbnail image
        print(f"   > 📥 Receiving new queue item for [{profile_name}]...")
        image_filename = f"{profile_name.replace(' ', '_')}_{message.id}.jpg"
        image_path = os.path.join(ASSETS_DIR, image_filename)
        await attachment.save(image_path)

        # Update the specific profile's JSON Queue
        queue_file = os.path.join(QUEUE_DIR, f"queue_{profile_name.replace(' ', '_')}.json")
        queue_data = []
        
        if os.path.exists(queue_file):
            with open(queue_file, "r") as f:
                try:
                    queue_data = json.load(f)
                except:
                    pass

        queue_data.append({
            "title": title,
            "image_path": image_path,
            "status": "pending"
        })

        with open(queue_file, "w") as f:
            json.dump(queue_data, f, indent=4)

        await message.channel.send(f"✅ **Success!** Added to `{profile_name}` Queue.\n🎬 **Title:** {title}")
        print(f"   > ✅ Queue updated for {profile_name}. Total pending: {len(queue_data)}")

if __name__ == "__main__":
    # Extract the universal token from the first valid profile in settings.json
    token = None
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            for profile in settings.values():
                bot_token = profile.get("discord_bot_token")
                if bot_token and "YOUR_" not in bot_token:
                    token = bot_token
                    break
    
    if token:
        client = AMBMasterAgent()
        client.run(token)
    else:
        print("❌ CRITICAL ERROR: Discord Bot Token not found or not updated in settings.json.")