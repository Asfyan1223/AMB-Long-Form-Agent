[Setup]
; --- Application Details ---
AppName=AMB Long Form Video Agent
AppVersion=1.0.0
AppPublisher=AMB ENTERPRISE
DefaultDirName={localappdata}\AMB Long Form Video Agent
DefaultGroupName=AMB Long Form Video Agent
OutputBaseFilename=AMBLongFormAgent_Setup_v1.0
Compression=lzma2
SolidCompression=yes

; Require admin rights to install into Program Files
PrivilegesRequired=admin
OutputDir=.\InstallerOutput

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; --- 1. The Main Executable & Internal Engine ---
; Grabs the highly optimized long-form executable and AI libraries
Source: "dist\AMB Long Form Video Agent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- 2. THE BYPASS: Forcing custom scripts into the app folder ---
; Ensures the .exe can "see" the raw scripts for the chunking and upload pipelines
Source: "audio_generator.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "social_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "cloud_logger.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "long_form_composer.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "script_generator.py"; DestDir: "{app}"; Flags: ignoreversion

; --- 3. Long-Form Asset Folders ---
Source: "font\*"; DestDir: "{app}\font"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "background_music\*"; DestDir: "{app}\background_music"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "reciter_photos\*"; DestDir: "{app}\reciter_photos"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; --- 4. Security Vault ---
Source: "credentials\*"; DestDir: "{app}\credentials"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; --- 5. Configuration Files ---
Source: "settings.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "client_secret.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "sheets_secret.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "token.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\AMB Long Form Video Agent"; Filename: "{app}\AMB Long Form Video Agent.exe"
Name: "{commondesktop}\AMB Long Form Video Agent"; Filename: "{app}\AMB Long Form Video Agent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AMB Long Form Video Agent.exe"; Description: "{cm:LaunchProgram,AMB Long Form Video Agent}"; Flags: nowait postinstall skipifsilent