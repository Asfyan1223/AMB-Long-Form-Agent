import os
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

def get_sheet(sheet_url):
    if not os.path.exists("sheets_secret.json"):
        print("   > ❌ Sheets Error: 'sheets_secret.json' is physically missing from this profile's folder.")
        return None
        
    if not sheet_url or "YOUR_" in sheet_url:
        print("   > ❌ Sheets Error: The Google Sheet URL in your settings is empty or invalid.")
        return None
        
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("sheets_secret.json", scope)
        client = gspread.authorize(creds)
        return client.open_by_url(sheet_url).sheet1
    except Exception as e:
        print(f"   > ❌ Google Sheets API Auth Error: {e}")
        return None

def setup_headers(sheet):
    try:
        first_row = sheet.row_values(1)
        if not first_row or first_row[0] != "Date":
            headers = ["Date", "Time (Local)", "Post Type", "Reference", "Status", "Raw_ISO"]
            sheet.insert_row(headers, 1)
            try:
                sheet.format('A1:F1', {
                    "backgroundColor": {"red": 0.15, "green": 0.68, "blue": 0.38}, 
                    "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}, "bold": True},
                    "horizontalAlignment": "CENTER"
                })
            except Exception: pass
    except Exception: pass

def get_last_post_time(sheet_url, post_type="QuranReel"):
    sheet = get_sheet(sheet_url)
    if not sheet: return "API_ERROR"  # 🌟 FIX: Return explicit error state
    try:
        setup_headers(sheet)
        rows = sheet.get_all_values()
        for row in reversed(rows):
            if len(row) >= 6 and row[2] == post_type:
                try: return datetime.fromisoformat(row[5])
                except: continue
        return None  # Only return None if the sheet is 100% working but empty
    except Exception as e:
        print(f"   > ❌ Sheets Read Error: {e}")
        return "API_ERROR"  # 🌟 FIX: Catch 500 errors and flag them

def log_post(personal_sheet_url, master_sheet_url, reference, post_type="QuranReel"):
    # 1. Prepare the exact data we want to log
    now = datetime.now() # Log local time
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    raw_iso = now.isoformat() 
    row_data = [date_str, time_str, post_type, reference, "✅ Uploaded", raw_iso]

    # 2. Write to the Profile's Personal Sheet
    personal_sheet = get_sheet(personal_sheet_url)
    if personal_sheet:
        try:
            setup_headers(personal_sheet)
            personal_sheet.append_row(row_data)
            print(f"   > ☁️ Logged successful post to Personal Sheet: {reference}")
        except Exception as e:
            print(f"   > ❌ Personal Sheets Write Error: {e}")
    else:
        print("   > ⚠️ Warning: Personal Sheet not configured or inaccessible.")

    # 3. Write to the Global Master Sheet
    master_sheet = get_sheet(master_sheet_url)
    if master_sheet:
        try:
            setup_headers(master_sheet)
            master_sheet.append_row(row_data)
            print(f"   > ☁️ Logged successful post to Master Sheet: {reference}")
        except Exception as e:
            print(f"   > ❌ Master Sheets Write Error: {e}")
    else:
         print("   > ⚠️ Warning: Master Sheet not configured or inaccessible.")

def get_gspread_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file('sheets_secret.json', scopes=scopes)
    return gspread.authorize(creds)

def push_settings_to_cloud(sheet_url, settings_dict):
    print("   > ☁️ Pushing Agency Profile to Google Sheets...")
    try:
        client = get_gspread_client()
        doc = client.open_by_url(sheet_url)
        try: sheet = doc.worksheet("Agency_Profile")
        except gspread.exceptions.WorksheetNotFound: sheet = doc.add_worksheet(title="Agency_Profile", rows="100", cols="5")
            
        sheet.clear()
        header = [["⚙️ Setting Name", "📊 Current Value"]]
        sheet.update('A1:B1', header)
        sheet.format('A1:B1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 0.8, 'green': 0.9, 'blue': 1.0}})
        
        rows = []
        for key, value in settings_dict.items(): rows.append([str(key), str(value)])
        sheet.update('A2', rows)
        
        sheet.update_acell('E1', 'DO_NOT_EDIT_RAW_JSON')
        sheet.update_acell('E2', json.dumps(settings_dict))
        print("   > ✅ Settings successfully backed up to the cloud!")
        return True
    except Exception as e:
        print(f"   > ❌ Cloud Sync Error: {e}")
        return False

def pull_settings_from_cloud(sheet_url):
    print("   > ☁️ Pulling Agency Profile from Google Sheets...")
    try:
        client = get_gspread_client()
        doc = client.open_by_url(sheet_url)
        sheet = doc.worksheet("Agency_Profile")
        raw_json = sheet.acell('E2').value
        if raw_json:
            settings_dict = json.loads(raw_json)
            print("   > ✅ Settings successfully restored from the cloud!")
            return settings_dict
        else:
            return None
    except Exception as e:
        print(f"   > ❌ Cloud Restore Error: {e}")
        return None

def sync_lf_timestamp(sheet_url, timestamp_str):
    print("   > ☁️ Syncing Long-Form timestamp to Google Sheets...")
    try:
        client = get_gspread_client()
        doc = client.open_by_url(sheet_url)
        try:
            sheet = doc.worksheet("Long-Form Logs")
        except gspread.exceptions.WorksheetNotFound:
            sheet = doc.add_worksheet(title="Long-Form Logs", rows="100", cols="5")
            
        sheet.update_acell('A1', timestamp_str)
        print("   > ✅ Long-Form timestamp synced to 'Long-Form Logs!A1'")
        return True
    except Exception as e:
        print(f"   > ❌ Long-Form Timestamp Sync Error: {e}")
        return False
