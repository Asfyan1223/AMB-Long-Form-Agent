import os
import sys
import time

def get_authenticated_youtube_service(token_path):
    if not token_path:
        print("   > ❌ YT Error: No token path provided!")
        return None

    try:
        from googleapiclient.discovery import build
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("   > ❌ YT Error: Missing required Google Libraries!")
        return None

    SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly']
    creds = None

    if os.path.exists(token_path):
        print("   > ✅ Existing token found. Attempting login...")
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            pass
    else:
        print("   > ⚠️ No token found in this vault. A browser window will open to authenticate.")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: 
            try:
                print("   > 🔄 Token expired. Refreshing automatically...")
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            if not os.path.exists('client_secret.json'): 
                print("   > ❌ YT Error: Missing client_secret.json in main directory!")
                return None
            print("   > 🌍 Opening browser for Google Authentication...")
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account consent')
            
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
        with open(token_path, 'w') as token_file:
            token_file.write(creds.to_json())
        print("   > 💾 New OAuth Token saved securely to profile vault.")

    try:
        youtube = build('youtube', 'v3', credentials=creds)
        return youtube
    except Exception as e:
        print(f"   > ❌ YT build service exception: {e}")
        return None

def compress_thumbnail(image_path, max_size_bytes=2000000):
    if not image_path or not os.path.exists(image_path):
        return image_path
        
    file_size = os.path.getsize(image_path)
    if file_size <= max_size_bytes:
        print(f"   > 🖼️ Thumbnail is within size limit ({file_size / 1024 / 1024:.2f} MB). No compression needed.")
        return image_path
        
    print(f"   > 🖼️ Thumbnail size ({file_size / 1024 / 1024:.2f} MB) exceeds limit. Starting compression...")
    quality = 90
    temp_compressed_path = os.path.join(os.path.dirname(image_path), "_compressed.jpg")
    
    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        while quality >= 10:
            img.save(temp_compressed_path, "JPEG", quality=quality)
            new_size = os.path.getsize(temp_compressed_path)
            print(f"     - Quality {quality}% -> {new_size / 1024 / 1024:.2f} MB")
            if new_size <= max_size_bytes:
                print(f"   > ✅ Thumbnail successfully compressed to {new_size / 1024 / 1024:.2f} MB at quality {quality}%.")
                return temp_compressed_path
            quality -= 5
            
        # Fallback if quality drops below 10 but still too large
        print("   > ⚠️ Thumbnail still exceeds size limit. Saving at minimal quality.")
        img.save(temp_compressed_path, "JPEG", quality=5)
        return temp_compressed_path
    except Exception as e:
        print(f"   > ❌ Thumbnail compression failed: {e}. Using original image.")
        return image_path

def upload_to_youtube(video_path, title, description, token_path, thumbnail_path=None, progress_callback=None):
    print(f"   > 🌐 Initiating YouTube Upload Module...")
    print(f"   > 🔐 Target Token Vault: {token_path}")
    
    youtube = get_authenticated_youtube_service(token_path)
    if not youtube:
        return

    try:
        try:
            channel_res = youtube.channels().list(part='snippet', mine=True).execute()
            if channel_res.get('items'):
                channel_name = channel_res['items'][0]['snippet']['title']
                print(f"   > 📺 VERIFIED CHANNEL LOGIN: Logged in as '{channel_name}'")
            else:
                print("   > 📺 VERIFIED CHANNEL LOGIN: Unknown Channel")
                
        except Exception as e:
            print(f"   > 🛑 FATAL AUTHENTICATION ERROR: Old or corrupted token detected!")
            print(f"   > 🗑️ Auto-deleting the bad token from: {token_path}")
            if os.path.exists(token_path):
                os.remove(token_path)
            print("   > ❌ UPLOAD ABORTED to prevent posting to the wrong channel.")
            return 

        # Clean metadata from short-form tags
        import re
        clean_title = re.sub(r'#shorts\b', '', title, flags=re.IGNORECASE).strip()
        clean_description = re.sub(r'#shorts\b', '', description, flags=re.IGNORECASE).strip()

        body = {
            'snippet': {
                'title': clean_title,
                'description': clean_description,
                'tags': ['Documentary', 'History', 'IslamicHistory', 'Quran', 'Educational', 'LongForm'],
                'categoryId': '27' # Education / Documentary Category
            },
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        from googleapiclient.http import MediaFileUpload
        # 10 MB chunks enable real-time progress reporting via next_chunk()
        media = MediaFileUpload(video_path, chunksize=10 * 1024 * 1024, resumable=True)
        import socket
        import http.client

        print("   > 🚀 Pushing video file to YouTube Servers...")
        req = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

        res = None
        last_pct = -1
        while res is None:
            try:
                status, res = req.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct != last_pct:
                        print(f"   > 📤 Uploading... {pct}%")
                        last_pct = pct
                        if progress_callback:
                            try:
                                progress_callback(pct)
                            except Exception:
                                pass
            except (ConnectionResetError, socket.error, http.client.RemoteDisconnected) as net_err:
                print(f"   > [!] Connection dropped: {net_err}. Retrying in 30 seconds...")
                time.sleep(30)
            except Exception as e:
                err_str = str(e)
                if "10054" in err_str:
                    print(f"   > [!] Connection dropped (WinError 10054). Retrying in 30 seconds...")
                    time.sleep(30)
                else:
                    raise e

        # Signal 100% completion to GUI
        if progress_callback:
            try:
                progress_callback(100)
            except Exception:
                pass


        print(f"   > ✅ YT Upload Success! Video ID: {res['id']}")
        
        # If thumbnail_path is provided and exists, upload it to the video
        if 'id' in res and thumbnail_path and os.path.exists(thumbnail_path):
            try:
                safe_thumbnail_path = compress_thumbnail(thumbnail_path)
                print(f"   > 🖼️ Uploading YouTube Thumbnail from: {safe_thumbnail_path}...")
                youtube.thumbnails().set(
                    videoId=res['id'],
                    media_body=MediaFileUpload(safe_thumbnail_path)
                ).execute()
                print("   > ✅ YT Thumbnail uploaded successfully!")
                
                # Cleanup the temporary compressed file if it was created
                if safe_thumbnail_path != thumbnail_path and os.path.exists(safe_thumbnail_path):
                    try:
                        os.remove(safe_thumbnail_path)
                        print("   > 🧹 Cleaned up temporary compressed thumbnail.")
                    except:
                        pass
            except Exception as thumb_err:
                print(f"   > ⚠️ YT Thumbnail upload failed: {thumb_err}")
    except Exception as e:
        print(f"   > ❌ YT Upload Exception: {e}")
